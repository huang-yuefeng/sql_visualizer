# Requirements Implemented — v2.9.5

> Current state of all features, fixes, and improvements.

---

## Node Identity Model

Every variable extracted from SQL is uniquely identified by a triple:

```
Node = (name, type, context)
```

| Component | Meaning | Example |
|-----------|---------|---------|
| `name` | Variable name (alias or auto-derived) | `total_score`, `t.amount` |
| `type` | One of 15 `VariableType` values | `aggregate`, `column`, `table` |
| `context` | Scoped location in the SQL nesting hierarchy | `TOP`, `CTE{calc}`, `TOP/union0` |

### Context Format

```
{}  = named scope (parallel, not deeper)
 /  = genuine nesting (child scope)
```

```
TOP                              root — outermost query
TOP/union0                       UNION branch 0 under root
TOP/subq1                        1st unnamed subquery under root
TOP/subq/s                        named subquery "s" under root
TOP/exists3                      3rd EXISTS under root
CTE{calc}                        CTE named "calc" — parallel to TOP
CTE{calc}/subq2                  2nd subquery inside CTE "calc"
CTE{calc}/subq2/exists5          5th EXISTS inside that subquery
```

### Rules

- **Same name + type + context** → one node (deduplication)
- **Same name + type + different context** → different nodes (preserved, e.g. UNION branches)
- **Columns** (`t.amount`) in WHERE and SELECT share context `TOP` → one node
- **Bare columns** (`entity_type` without table prefix) in subqueries → own context → own node
- **Computed values** in UNION branches → different contexts → different nodes

### 15 Variable Types

| Category | Types |
|----------|-------|
| Data Sources | `table`, `view`, `cte`, `subquery`, `virtual_table` |
| DML Targets | `merge_target` |
| Set Operations | `union_branch` |
| Column References | `column`, `cte_column` |
| Computed Values | `aggregate`, `window`, `case`, `transform`, `expression` |
| Literals | `literal` |

---

## Architecture

```
SQL Text → sqlglot parse → variable_extractor_v2 → dependency_graph
    → graph_service (Cytoscape JSON) → FastAPI → React + Cytoscape.js
```

- **Backend**: FastAPI + sqlglot (MySQL dialect)
- **Frontend**: React + Vite + Cytoscape.js
- **Tests**: 254 tests in `backend/tests/`
- **Version**: See `/VERSION`

---

## R1 — Variable Extraction (15 types)

**Description:** Parse SQL and classify every named variable by its role in data flow.

**Node types** (aligned with SQL data objects):

| Category | Types |
|----------|-------|
| Script | `script` (multi-view only — entire SQL file) |
| Tables | `table`, `view`, `virtual_table`, `cte`, `subquery`, `merge_target`, `union_branch` |
| Columns | `column`, `cte_column` |
| Computed | `aggregate`, `window`, `case`, `transform`, `expression`, `literal` |

**Solution:** Role-based Identifier walking — every `Identifier` AST node is classified by its parent node role. Handles any SQL sqlglot can parse.

**Files:** `backend/app/extractor/variable_extractor_v2.py`, `backend/app/models/variable.py`, `backend/app/models/sql_model.py`

---

## R2 — Dependency Graph (13 edge types)

**Description:** Build directed edges showing data flow between variables.

**Edge types:**

| Edge | Direction | Meaning |
|------|-----------|---------|
| `TABLE_FLOW` | table alias → output container | Table feeds SELECT/CTE output |
| `ALIAS` | original → alias | Name reference (users → u) |
| `REF` | column → expression | Direct column reference |
| `AGGREGATE` | column → aggregate | SUM/COUNT/AVG |
| `TRANSFORM` | column → function | COALESCE/CAST/CONCAT |
| `WINDOW` | column → window | ROW_NUMBER/RANK/LAG |
| `COMPUTED` | column → CASE | CASE WHEN result |
| `SCHEMA` | table/CTE/VT → column | Structural ownership |
| `INDIRECT` | defined var → bare ref | HAVING→SELECT name match |
| `FILTER` | WHERE/JOIN ON column → anchor | Row filtering |
| `DML` | source → target table | INSERT/UPDATE/DELETE/MERGE |
| `SET_OP` | union branch → parent | UNION/INTERSECT/EXCEPT |
| `SUBSET` | component → main | Safety net bridge |

**Construction order (top-down):**
1. TABLE_FLOW — table-to-table connections (high-level skeleton)
2. ALIAS — name resolution
3. Column edges — REF/AGGREGATE/TRANSFORM/WINDOW/COMPUTED
4. SCHEMA — structural ownership
5. INDIRECT — bare name references
6. FILTER — WHERE/HAVING conditions
7. SUBSET — disconnected component bridge

**Files:** `backend/app/extractor/dependency_graph.py`, `backend/app/services/graph_service.py`

---

## R3 — Frontend Visualization

**Description:** Interactive Cytoscape.js graph with dark-theme UI.

**Three-panel layout:**
- **Left sidebar:** Script list, node/edge type filters, legend (16 node + 13 edge types)
- **Center:** `cose` layout graph with hover/click/dim highlighting
- **Right:** Detail panel showing variable metadata, SQL expressions, dependencies

**Legend ordering (by conceptual breadth):**
- ── Script ── (multi-view)
- ── Tables ──
- ── Columns ──
- ── Computed ──

**View modes:** Tables (default, shows table-level flow) / Full (shows all nodes/edges)

**Files:** `frontend/src/App.jsx`, `frontend/src/utils/graphStyles.js`, `frontend/src/styles/app.css`

---

## R4 — Single-Script Upload & Analysis

**Description:** Upload SQL → auto-analyze → render graph.

**Buttons:** `[Multi SQL] [Single SQL] [Paste SQL] [Filter] [Show SQL] [Tables▼] [Fit]`

- **Single SQL**: Upload one `.sql` file, auto-renders graph
- **Paste SQL**: Quick testing via prompt
- **Filter**: CSV for IO graph path finding (single-script) or table name filtering (multi-script)
- **Show SQL**: Toggle bottom panel with original SQL source

---

## R5 — Multi-Script View

**Description:** Upload multiple SQL files → compound meta-graph showing data lineage between scripts.

**Features:**
- Script circles (110×65px ellipses) with dashed gold border
- `data_lineage` edges (bright green `#00FF88`): producer script → consumer script, with table names as labels
- `shared_input` edges (bright blue `#5DADE2`): scripts sharing the same source table
- **Click** any script circle → opens as single-script view with pre-built graph
- **Filter** button: upload table name list → only scripts containing those tables shown
- **Multi tag** in sidebar: persists for easy switching between multi and single views
- **Progress bar**: Shows elapsed time during multi-script analysis

**Backend:** Input/output table classification per script (`_classify_tables`), alias filtering on edge labels (`_originals`), data lineage detection (output→input table matching).

**Files:** `backend/app/services/multi_script_service.py`, `frontend/src/App.jsx`, `frontend/src/utils/graphStyles.js`

### R5a — Layer Layout + Tree View

**Description:** Alternative multi-script layout with BFS-based layering, multi-color tree highlighting, and tree detail view.

**Layer Layout:**
- Dropdown selector: `[Layer ▼] [Ring] [Cose]`
- BFS from filter CSV root nodes — nodes positioned in horizontal layers by distance
- Undirected BFS traversal of the meta-graph adjacency

**Tree Hover Highlighting (Layer mode):**
- Hover a node → BFS from that node → highlight full connected component, dim everything else
- **Multi-tree coloring:** When a node belongs to multiple trees (different filter roots), each tree gets a distinct color (`tree-0` through `tree-7` classes with unique border/edge colors)
- Shared nodes show all tree colors overlapping; unshared parts of each tree are colored distinctly
- Mouseout clears all tree classes and dimming

**Tree Detail View (Layer mode):**
- Double-click a script circle → compute the connected tree component via BFS
- If tree has ≥2 scripts: opens a filtered multi-view showing only the scripts in that tree (as `🌳 Tree: script_name` sidebar tag)
- If tree has only 1 script (isolated): falls back to opening the script's full single-script graph
- Tree view shows summary: total variables, dependencies, input/output tables across all tree scripts

**Files:** `frontend/src/App.jsx`, `frontend/src/utils/graphStyles.js`

---

## R6 — Topological Integrity Checks (10 checks)

**Description:** Automatic verification that every generated graph is well-formed.

| Check | Type | What it verifies |
|-------|------|-----------------|
| `isolated_nodes` | Hard error | Every node has edges (≥2 for columns, ≥1 for tables) |
| `disconnected_components` | Hard error | Graph is one connected piece |
| `duplicate_nodes` | Hard error | No (name, type) duplicates |
| `duplicate_edges` | Hard error | No (source, target, relationship) duplicates |
| `duplicate_table_names` | Hard error | CTE and TABLE don't coexist for same name |
| `column_connectivity` | Hard error | Table-prefixed columns have SCHEMA from their table |
| `component_link_usage` | Info | Reports table→table SUBSET edges |
| `node_name_uniqueness` | Info | (name, type) dedup verification |
| `ambiguous_base_names` | Info | Same base name across different types (e.g., CTE + its VT) |
| `alias_edges` | Info | Table aliases have ALIAS edge to original |

**Files:** `backend/app/services/topology_checker.py`

---

## R7 — Edge Validity Tests (30 tests)

**Description:** Every edge must correspond to a real data flow — no spurious edges.

| Test class | Tests | What it checks |
|------------|-------|---------------|
| `TestNoFilterOnSelectSources` | 7 | SELECT expression sources never get bogus FILTER edges |
| `TestSyntheticEdges` | 2 | SUBSET edges are safety-net, not data flow |
| `TestEdgeTypeValidity` | 6 | Each edge type connects appropriate node types |
| `TestAllEdgesValidAcrossSamples` | 15 | All 5 core samples: no bogus FILTER, valid endpoints, TABLE_FLOW ≥ FROM count |

**Files:** `backend/tests/test_edge_validity.py`

---

## R8 — Type Styling Coverage (11 tests)

**Description:** Every node type must have styling in both backend and frontend.

| Test | What it checks |
|------|---------------|
| `test_all_types_in_node_styles` | `graph_service.py` NODE_STYLES has all 15 types |
| `test_all_types_in_cytoscape_selectors` | `graphStyles.js` has selector for every type |
| `test_all_types_in_frontend_colors` | `App.jsx` color map covers all types |
| `test_all_types_in_frontend_node_shapes` | `App.jsx` NODE_SHAPES covers all types |
| `test_all_types_in_frontend_filter` | `App.jsx` VT filter has all types |
| Plus shape name validity, size constraints | |

**Files:** `backend/tests/test_type_styling.py`

---

## R9 — Workflow Tests (17 tests)

**Description:** End-to-end ETL pipeline tests with real multi-script scenarios.

**Test data:** 5-step ETL pipeline (`samples/multi_workflow/`):
```
step1_load_orders → step2_enrich_customers → step3_join → step4_aggregate → step5_report
```

| Test class | Tests | What it checks |
|------------|-------|---------------|
| `TestSingleScriptTableFlow` | 3 | Every FROM alias has TABLE_FLOW, no isolated tables, correct direction |
| `TestSingleScriptColumnFlow` | 2 | Every column ≥2 edges, output columns have SCHEMA from VT |
| `TestEdgeDirection` | 4 | AGGREGATE/DML/ALIAS/FILTER follow data flow direction |
| `TestMultiScriptWorkflow` | 6 | Data lineage chain, edge labels, direction, I/O classification |
| `TestProgressTracking` | 2 | Performance benchmarks |

**Files:** `backend/tests/test_workflow.py`, `samples/multi_workflow/`

---

## R10 — Node Type Per-Type Coverage (53 tests)

**Description:** Every one of the 15 variable types must be reachable from real SQL.

Each type has a dedicated test class with SQL that produces it. Also tests SELECT INTO, CTAS, DML targets, INSERT VALUES.

**Files:** `backend/tests/test_node_types.py`

---

## R11 — Edge Type Per-Type Coverage (36 tests)

**Description:** Every one of the 13 edge types must appear across test files.

Each edge type has dedicated tests verifying its creation, plus regression tests for fixed bugs (CTE dedup, bare column dedup, CASE source columns, EXISTS tables, JOIN edges, MERGE DML).

**Files:** `backend/tests/test_edge_types.py`

---

## R12 — Key Bug Fixes

| Bug | Fix |
|-----|-----|
| INSERT target `defined_in="FROM"` instead of `"INSERT"` | Rewrote `_walk_insert()` with explicit INSERT marking |
| UPDATE/DELETE DML edges missing | DML phase now finds source columns from any variable type |
| CTE VT naming collision (`⟐ customer_total_return` duplicate) | CTE SELECTs skip VT creation — CTE node serves as container |
| Tables view hiding multi-script nodes | View mode filter skips meta-graph (`!multiView` guard) |
| ALIAS direction wrong (alias→original) | Reversed to original→alias (data source direction) |
| Container `display:none` preventing Cytoscape init | Changed to `opacity:0` with `pointer-events:none` |
| Layout flash on first render | `cy.batch()` adds elements + runs layout atomically |
| Stale cache with old type names | Version-based cache key invalidation |
| Subquery NOT IN columns isolated | Subquery inner SELECT fully walked |

---

## R13 — Sample Library

**Basic queries (5):** `query1-5.sql`

**GPS financial queries (16):** `fin_query1-16.sql`

**TPC-DS benchmark (99):** `q1-99.sql` in `samples/tpcds/`

**Multi-script workflow (5):** `step1-5.sql` in `samples/multi_workflow/`

**IO CSVs:** `samples/financial/io_csv/`, `samples/tpcds/io_csv/`

---

## Test Summary

| File | Tests | Focus |
|------|-------|-------|
| `test_node_types.py` | 53 | Per-type coverage |
| `test_edge_types.py` | 36 | Per-edge coverage + regression |
| `test_edge_validity.py` | 30 | No spurious edges |
| `test_type_styling.py` | 11 | Frontend/backend style coverage |
| `test_workflow.py` | 17 | ETL pipeline + data flow direction |
| `test_graph_integrity.py` | 22 | Topology checks × all samples |
| `test_variable_extractor.py` | 17 | Core extraction |
| `test_dependency_graph.py` | 6 | Edge creation |
| `test_complex_samples.py` | 30 | DWH analytics (13 scripts) |
| `test_analytical_samples.py` | 10 | TPC-DS analytical |
| `test_github_inspired_samples.py` | 22 | Real-world GPS patterns |
| **Total** | **254** | |

**Run:** `cd backend && ./venv/bin/python -m pytest tests/ -q`

---

## R14 — Server-Side Progress Logging in Frontend

> **Priority:** P2 | **Status:** ✅ Implemented | **Version:** v3.3.73 | **Date:** 2026-07-23

**Description:** Stream pipeline progress logs from backend to frontend in real-time, so users see what's happening during long-running analysis operations (critical for air-gapped deployment with large SQL scripts).

**Problem:** Backend already logs pipeline stages (`parse → extract → deps → graph`) to stderr via `backend/app/services/logger.py`, but these are invisible to the frontend user. Large scripts can take 10-30+ seconds with zero UI feedback.

---

### Implementation Decisions

**Q1 — SSE vs WebSocket?** SSE chosen: unidirectional (server→client), HTTP-native, auto-reconnect built into browsers. Simpler than WebSocket for push-only logging.

**Q2 — LogPanel placement?** **Option A — Bottom bar.** Collapsible panel at the bottom of the DataFlowApp layout. Collapsed: single-line status showing latest message with stage badge. Expanded: scrollable history with Clear/Copy buttons.

**Q3 — When does streaming start?** EventSource connects on workspace open (when `wsId` is set). Logs from any operation (search, L2 graph build, indexing) are streamed. Cached operations show `api_request` logs; fresh analysis shows full `parse → extract → deps → graph → done` pipeline.

**Q4 — Thread safety?** `run_full_analysis` runs in FastAPI's thread pool (sync endpoint). `asyncio.Queue` is not thread-safe, so `queue.Queue` (thread-safe) is used. SSE endpoint polls via `loop.run_in_executor(None, q.get(timeout=1.0))` every 1 second, with keepalive comments between polls.

**Q5 — Queue lifecycle?** Created lazily on first log call for a workspace. Destroyed on workspace delete. Bounded to 500 messages.

---

### Backend

**SSE endpoint:** `GET /api/workspace/{ws_id}/logs`
- Returns `text/event-stream` with `Cache-Control: no-cache`, `X-Accel-Buffering: no`
- Drains existing messages, then polls with 1s timeout + keepalive
- File: `backend/app/routers/logs.py`

**Logger (`backend/app/services/logger.py`):**
- `_log_queues: dict[str, queue.Queue]` — per-workspace thread-safe queues
- `_push(ws_id, stage, message)` — writes to stderr + puts into queue if ws_id present
- All existing log functions (`pipeline_start`, `stage_extract`, etc.) accept optional `ws_id` parameter
- `ensure_queue()` / `remove_queue()` for lifecycle management

**Adapter (`backend/app/extractor/adapter.py`):**
- `run_full_analysis(sql_text, script_name, ws_id=None)` — passes `ws_id` to all log calls

**Dataflow service (`backend/app/services/dataflow_service.py`):**
- Cache hits: log `stage_graph` with node/edge counts
- Search: log `api_request` with table/field info
- All `run_full_analysis` calls pass `ws_id`

**Cleanup:** `DELETE /api/workspace/{ws_id}` calls `remove_queue(ws_id)`

---

### Frontend

**LogPanel (`frontend/src/components/LogPanel.jsx`):**
- Props: `wsId`, `visible`
- `EventSource` connects to `/api/workspace/{wsId}/logs` on mount, disconnects on unmount
- Collapsed bar: stage dot + latest message + toggle arrow (▲▼)
- Expanded list: monospace, scrollable, auto-scrolls to newest entry
- Color-coded stage badges:
  - `parse` = gray (#95A5A6), `extract` = blue (#3498DB)
  - `deps` = purple (#8E44AD), `graph` = teal (#1ABC9C)
  - `done` = green (#27AE60), `error` = red (#E74C3C), `info` = dark gray (#7F8C8D)
- Clear button: empties log list
- Copy button: copies all log messages to clipboard

**Integration (`frontend/src/DataFlowApp.jsx`):**
- `<LogPanel wsId={wsId} visible={true} />` placed at bottom of `.dataflow-layout`
- Renders only when `wsId` is set (workspace is open)

**Styles (`frontend/src/styles/app.css`):**
- Dark theme (#1a1a2e background), monospace font
- Custom scrollbar styling, hover highlights
- 220px max-height when expanded, 28px collapsed

---

### Known Gaps → All Resolved (v3.3.75)

| # | Gap | Fix |
|---|-----|-----|
| 1 |  always 0 | Changed to  instead of nonexistent  |
| 2 | Timing was fake (total/4 each) | Added real per-stage  deltas:  after extract,  after deps,  after graph |
| 3 | Zero-valued categories hidden | Removed  filter in  so all categories always appear for complete picture |

### Known Gaps → All Resolved (v3.3.75)

| # | Gap | Fix |
|---|-----|-----|
| 1 | stmt_count always 0 | Changed to sum(_count_statement_types(sql_text).values()) instead of nonexistent extract_result.statements |
| 2 | Timing was fake (total/4 each) | Added real per-stage time.time() deltas: t1 after extract, t2 after deps, t3 after graph |
| 3 | Zero-valued categories hidden | Removed if v > 0 filter in _kv() so all categories always appear for complete picture |

### Acceptance Criteria

- [x] Pipeline stages appear in real-time during analysis (not batched)
- [x] Final message "✅ PIPELINE DONE elapsed=Xms" shown
- [x] Errors appear in red inline
- [x] Panel collapses to single-line status bar (click to toggle)
- [x] Works for single-script and multi-script (workspace) loading
- [x] Works in air-gapped deployment (no external CDN dependencies)
- [x] No performance degradation from SSE connection (1 poll/second, keepalive)

### Files Changed

| File | Change |
|------|--------|
| `backend/app/services/logger.py` | Added thread-safe queue.Queue support, optional ws_id to all functions |
| `backend/app/routers/logs.py` | **New** — SSE endpoint with polling generator |
| `backend/app/main.py` | Registered logs router |
| `backend/app/extractor/adapter.py` | `run_full_analysis` accepts ws_id, passes to logger |
| `backend/app/services/dataflow_service.py` | Cache-hit graph logs, api_request logs, ws_id propagation |
| `backend/app/routers/workspace.py` | Queue cleanup on workspace delete |
| `frontend/src/components/LogPanel.jsx` | **New** — collapsible log panel with EventSource |
| `frontend/src/DataFlowApp.jsx` | Integrated LogPanel at bottom |
| `frontend/src/styles/app.css` | ~60 lines of log panel styling |

---

## R15 — Script Profile Summary for Remote Debugging

> **Priority:** P2 | **Status:** ✅ Implemented (all 3 gaps fixed) | **Version:** v3.3.75 | **Date:** 2026-07-23

**Description:** After each SQL script is analyzed during folder indexing, emit a compact ASCII-boxed "profile" summary containing enough structural metadata to allow an external developer to mock a structurally similar SQL script — without needing access to the original SQL text.

**Problem:** The air-gapped machine contains large proprietary SQL scripts that cannot be copied out. Only screen photographs are available. A photograph of a compact statistics block provides enough information to reproduce the structure.

**When:** After folder indexing completes for each script (before user starts searching). Profiles appear in both Docker stderr and frontend LogPanel via SSE.

---

### Implementation Decisions

**Q1 — Where does the profile appear?** Both stderr (Docker logs) AND frontend LogPanel via SSE. Users see profiles accumulating in the LogPanel during folder indexing.

**Q2 — When is it emitted?** After each script's pipeline completes during folder indexing (`index_scripts`). Not on every cached read — only on first analysis. The profile block is pushed to SSE queue with stage=`"profile"`.

**Q3 — Data sources for counts:**

| Category | Source | Already available? |
|----------|--------|--------------------|
| File metrics | `sql_text` length, line count, statement count | ✅ Partially — statements counted during parse |
| Statement types | `_count_statement_types()` — scans top-level SQL keywords via regex | ❌ New — added to adapter.py |
| Clause profile | `_count_clauses()` — regex for FROM/JOIN/WHERE/GROUP BY/ORDER BY/HAVING | ❌ New |
| Function profile | `_count_functions()` — regex for aggregate/transform/window function names | ❌ New |
| Variable profile | `extract_result.variables` → counts by `VariableType` | ✅ Already in pipeline |
| Edge profile | `dependencies` → counts by `relationship` | ✅ Already in pipeline |
| Nesting | `_count_nesting()` — counts subquery depth and CTE count from sqlglot AST | ❌ New |
| Performance | `time.time()` deltas per stage | ✅ Already tracked |

**Q4 — Frontend rendering?** No changes needed. LogPanel already uses monospace font and renders raw text. Box-drawing characters (┌─│└) display correctly as-is.

---

### Backend

**Logger (`backend/app/services/logger.py`):**
- `pipeline_profile(script_name, counts, ws_id=None)` — emits ASCII box to stderr + SSE queue
- Stage tag: `"profile"` (color: teal #1ABC9C in frontend)
- Box width: 80 characters (fits standard terminal / photograph)

**Adapter (`backend/app/extractor/adapter.py`):**
- Calls `pipeline_profile()` after `pipeline_done()` when `ws_id` is available
- Collects counts from existing pipeline data + new regex-based counters
- Regex approach chosen over sqlglot AST traversal: faster, no parse overhead, works with fallback-parsed SQL

**Example output:**
```
┌─ SCRIPT PROFILE: step3_join_orders_customers.sql ──────────────────────────┐
│ Size: 339B  Lines: 7  Stmts: 2    Parse: 1ms  Extract: 2ms  Deps: 1ms  Graph: 1ms  Total: 5ms │
│ Stmts: INSERT=1 SELECT=1                                                     │
│ Clauses: FROM=2 JOIN=1 WHERE=1 GROUP_BY=0 ORDER_BY=0 HAVING=0 CTE=0         │
│ Funcs: aggregate=0 transform=0 window=0 subquery=0                           │
│ Vars: table=3 view=0 cte=0 column=6 virtual_table=1 expression=0 aggregate=0 transform=0 window=0 case=0 │
│ Edges: TABLE_FLOW=4 ALIAS=2 SCHEMA=15 FILTER=1 JOIN=2 DML=1                  │
│ Nesting: max_depth=0 subqueries=0 ctes=0                                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Files Changed

| File | Change |
|------|--------|
| `backend/app/services/logger.py` | Added `pipeline_profile()` with box-drawing output |
| `backend/app/extractor/adapter.py` | Added `_count_statement_types()`, `_count_clauses()`, `_count_functions()`, `_count_nesting()`; call `pipeline_profile` after `pipeline_done` |

### Known Gaps → All Resolved (v3.3.75)

| # | Gap | Fix |
|---|-----|-----|
| 1 |  always 0 | Changed to  instead of nonexistent  |
| 2 | Timing was fake (total/4 each) | Added real per-stage  deltas:  after extract,  after deps,  after graph |
| 3 | Zero-valued categories hidden | Removed  filter in  so all categories always appear for complete picture |

### Known Gaps → All Resolved (v3.3.75)

| # | Gap | Fix |
|---|-----|-----|
| 1 | stmt_count always 0 | Changed to sum(_count_statement_types(sql_text).values()) instead of nonexistent extract_result.statements |
| 2 | Timing was fake (total/4 each) | Added real per-stage time.time() deltas: t1 after extract, t2 after deps, t3 after graph |
| 3 | Zero-valued categories hidden | Removed if v > 0 filter in _kv() so all categories always appear for complete picture |

### Acceptance Criteria

- [x] Profile block emitted after every pipeline_done during folder indexing
- [x] Block fits within 80-character width
- [x] All 8 data categories present
- [x] Profile appears in both Docker stderr and frontend LogPanel
- [x] Developer can use one photograph to generate structurally equivalent mock SQL
- [x] Zero performance overhead: regex counts take <1ms

---

## R16 — Filter CSV Diagnostic Logging

> **Priority:** P2 | **Status:** ✅ Implemented | **Version:** v3.3.94 | **Date:** 2026-07-27

**Description:** When user uploads filter CSV files (script→table, table→column), emit a diagnostic profile block to the LogPanel showing what was parsed — so the user can screenshot it for remote debugging when the filter returns unexpected results (e.g., "0 tables, 0 fields").

### Problem

The filter silently returns 0 results if the CSV headers or data don't match expectations. The user has no visibility into what was parsed. They can't tell whether:
- CSV headers were recognized
- Data rows were parsed
- Table/script names match the index
- The issue is in the CSV format or in the data

### Solution

When `POST /workspace/{ws_id}/filter-config` processes CSV files, push a diagnostic block to the SSE log queue (stage: `"profile"`), same format as R15 script profiles:

```
┌─ FILTER DIAGNOSTIC ────────────────────────────────────────────────────────┐
│ File 1 (script_table): test.csv  rows=7  headers=SCRIPT_NAME,TABLE_NAME      │
│   Sample rows: step1_load_orders.sql→raw_orders                              │
│                step2_enrich_customers.sql→crm_customers                       │
│   Parsed: 7 scripts, 6 tables                                                 │
│ File 2 (table_col): test2.csv  rows=10  headers=SYSTEM,TABLE_NAME,COL_NAME    │
│   Sample rows: ETL→raw_orders→order_id                                        │
│                ETL→stg_orders→amount                                          │
│   Parsed: 10 columns, 5 tables                                                │
│ Result: 5 tables, 6 fields in filtered index                                  │
│ ⚠ No data parsed from script_table. Check headers: SCRIPT_NAME, TABLE_NAME   │  ← only if 0 rows
└──────────────────────────────────────────────────────────────────────────────┘
```

### Implementation

In `workspace.py:upload_filter_config`, after parsing each CSV, push a profile message:

```python
from app.services.logger import _push, _ts

# After parsing script_table:
_push(ws_id, "profile", f"┌─ FILTER DIAGNOSTIC ─{'─'*60}┐")
_push(ws_id, "profile", f"│ File 1 (script_table): {script_table.filename}  rows={row_count}  headers={headers}")
# ... sample rows, counts ...

# After parsing table_col:
_push(ws_id, "profile", f"│ File 2 (table_col): {table_col.filename}  rows={row_count}  headers={headers}")
# ... sample rows, counts ...

# After filtering:
_push(ws_id, "profile", f"│ Result: {len(filtered_ti)} tables, {len(filtered_fi)} fields")
_push(ws_id, "profile", f"└{'─'*78}┘")
```

### Diagnostics to include

| Item | Source | Purpose |
|------|--------|---------|
| File name | `file.filename` | Identify which CSV |
| Row count | `len(rows)` | Confirm data was read |
| Column headers | `DictReader.fieldnames` | Verify headers match expected |
| Sample rows (first 2) | First 2 parsed rows | Quick visual check of data |
| Parsed counts | `len(allowed_scripts)`, etc. | How many unique values |
| Filter result | `len(filtered_ti)`, `len(filtered_fi)` | Final match count |
| Warning (if 0) | Conditional | "Check headers: SCRIPT_NAME, TABLE_NAME" |

### Acceptance Criteria

- [x] Diagnostic block appears in LogPanel after "Apply Filter" is clicked
- [x] Shows file names, row counts, column headers, sample rows, parse counts
- [x] Shows filter result (N tables, M fields)
- [x] Shows warning when 0 rows parsed from a CSV
- [x] Block is photographable (80-char width, ASCII box)
- [x] Works with 0, 1, or 2 CSV files uploaded
- [x] No performance impact (push happens once, not per script)

### Known Gaps — Filter Matching (from OCR analysis)

The diagnostic block correctly shows parsed data, but matching fails even after the `basename` fix (v3.3.89). From OCR of a real deployment screenshot:

| CSV | Parsed | Match Result |
|-----|--------|-------------|
| script_table (map.csv) | 48 scripts, 8 tables | — |
| table_col (dict.csv) | 2385 columns, 81 tables | — |
| **Combined** | — | **0 tables, 0 fields** ❌ |

**Root cause — three levels of name mismatch:**

| Mismatch | Index stores | CSV has | Fix status |
|----------|-------------|---------|------------|
| Path prefix | `folder/script.sql` | `script.sql` | ✅ Fixed (basename) |
| Path prefix (reversed) | `script.sql` | `folder/script.sql` | ✅ Fixed (basename) |
| **File extension** | `script.sql` | `script` | ✅ Fixed (v3.3.91) |

The CSV script names lack the `.sql` extension. The index stores `script_name.sql`, but the CSV has `script_name`. The `basename` fix doesn't cover extension mismatch.

**Required fix — also match by adding `.sql` suffix:**

In the CSV parsing loop, also try adding `.sql` to script names:

```python
if sn: 
    allowed_scripts.add(sn)
    allowed_scripts.add(os.path.basename(sn))
    if not sn.endswith('.sql'):
        allowed_scripts.add(sn + '.sql')       # try with extension
        allowed_scripts.add(os.path.basename(sn) + '.sql')
```

This handles all three mismatch cases: path prefix (both directions) and missing file extension.

### Filter Diagnostic: Scope Expansion Warning

When both `script_table.csv` and `table_col.csv` are uploaded, the diagnostic should warn if `table_col.csv` introduces many new tables not in `script_table.csv`'s scope:

```
┌─ FILTER DIAGNOSTIC ───────────────────────────────────────────────────┐
│ File 1 (script_table): ... rows=48  Parsed: 96 scripts, 8 tables       │
│ File 2 (table_col): ... rows=3136  Parsed: 2385 columns, 81 tables     │
│ ⚠ table_col.csv added 73 new tables not in script_table scope          │
│   (8 from script_table + 73 from table_col = 81 total in scope)        │
│   Consider: move tables from table_col to script_table instead          │
│ Result: 60 tables, 537 fields in filtered index                         │
└────────────────────────────────────────────────────────────────────────┘
```

This tells the user: "Your `table_col.csv` is adding 73 extra tables. If you want only 8 tables, move those table names to `script_table.csv` instead."

---

## R17 — Search Diagnostic Logging After Filter

> **Priority:** P2 | **Status:** Implemented | **Version:** v3.3.92v3.3.92 | **Date:** 2026-07-27

**Description:** When a search returns empty results after a filter is applied, emit a diagnostic block to the LogPanel showing why — so the user can screenshot it for remote debugging.

### Problem

User applies a filter CSV, then searches for a table+field. The search returns 200 but no results:
```
POST /workspace/9c81e5042b96/search → 200 table=ods_gdc_split_fg_rating field=borrower_ids
```
No indication of WHY: is the table in the filtered index? Is the field? Are there matching scripts? The user can't tell whether the search failed because of the filter, a typo, or missing data.

### Key design constraint

When a filter is active, the autocomplete dropdowns AND the search scope must be limited to filtered tables/fields only. The filter narrows the entire index — tables not in the CSV should not appear in autocomplete, and searching them should explicitly report they're outside the filter scope.

### Solution

After each search, push a diagnostic block to the SSE log queue (stage: `"profile"`):

```
┌─ SEARCH DIAGNOSTIC ──────────────────────────────────────────────────────────┐
│ Query: table=ods_gdc_split_fg_rating  field=borrower_ids                      │
│ Filter active: YES  (81 tables, 2385 fields in scope)                         │
│ Table in filtered index: NO ← table not in CSV filter                         │
│ Field in filtered index: NO ← field not in CSV filter                         │
│ Matching scripts: 0                                                            │
│ ⚠ Table not in filter scope — add it to script_table.csv or clear filter      │
└────────────────────────────────────────────────────────────────────────────────┘
```

If filter is NOT active, show the full index scope instead:
```
│ Filter active: NO  (full index: 500 tables, 12000 fields)                     │
│ Table in index: YES  (12 scripts)                                              │
│ Field in index: YES  (5 scripts)                                               │
│ Matching scripts: 0  (no script contains both)                                 │
│ ⚠ Table and field exist but no script contains both — try different field      │
```

### Data to include

| Item | Source | Purpose |
|------|--------|---------|
| Query params | Search request | What was searched |
| Filter state | `filtered_index.json` exists? | Is filter active |
| Filter scope | `len(filtered_ti)`, `len(filtered_fi)` | How many tables/fields in scope |
| Table hit | `table in filtered_ti` or `table_index` | Is table in scope |
| Field hit | `field in filtered_fi` or `field_index` | Is field in scope |
| Script count | `len(tdata.scripts)` | How many scripts reference this |
| Warning message | Conditional logic | Actionable suggestion |

### Files

`backend/app/routers/dataflow.py` — `search_dataflow` endpoint: emit diagnostic after search

### Acceptance Criteria

- [x] Diagnostic block appears in LogPanel after every search
- [x] Shows: query, filter state, filter scope, table hit, field hit, script count, suggestion
- [x] Works when filter is active AND when filter is cleared
- [x] Clearly distinguishes "table/field not in filter scope" vs "no matching scripts"
- [x] Block is photographable (80-char width, ASCII box)

---

## R18 — Field-Level Data Flow Extraction

> **Priority:** P2 | **Status:** Implemented (v3.3.95) | **Date:** 2026-07-28

**Description:** When a user searches for a specific field (`table=T, field=Y`), filter both L1 and L2 graphs to show only nodes and edges on the data flow path of field Y. UI/UX unchanged — same graph, same L1/L2 interactions, fewer elements.

### Formal Definition

See [`wiki/DATAFLOW_FORMAL_DEFINITION.md`](../wiki/DATAFLOW_FORMAL_DEFINITION.md) — Field-Level Data Flow section for the complete 16 edge-type rule table, Lineage Set R definition, worked example, and design framework.

See [`wiki/REQUIREMENTS_TRACEABILITY.md`](../wiki/REQUIREMENTS_TRACEABILITY.md) — for traceability mapping.

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
│                                                           │
│ search_dataflow(table, field, lineage_mode=true)          │
│   → same pipeline + field-level filter at the end        │
└──────────────────────────────────────────────────────────┘
```

### Lineage Set R

R is the transitive closure of queried field Y, computed by applying 16 edge-type-specific rules. Key principles:

- **Production edges** (REF/TRANSFORM/AGGREGATE/WINDOW/COMPUTED/DML): propagate bidirectionally
- **Structural edges** (SCHEMA/ALIAS/TABLE_FLOW): provide context, SCHEMA↓ is production-filtered
- **Conditional edges** (JOIN/FILTER): only include nodes already in R via production edges
- **Always edges** (SUBSET/SET_OP/CORRELATED/INDIRECT): always followed for connectivity

### What Changes

| | Current | Desired |
|---|---|---|
| L1 graph | All scripts + fields for table T | Only fields in Y's lineage chain |
| L2 graph | All fields in table T | Only Y's upstream sources + downstream targets |
| UI/UX | Click L1→L2, click edge→SQL | Unchanged |
| Unrelated same-table fields | Shown | Hidden |

### Example

`INSERT INTO stg_customers SELECT c.customer_id, c.full_name, c.segment FROM crm_customers c WHERE c.region='NA'`
**Query:** `table=stg_customers, field=customer_id`

| Field | Shown? | Reason |
|-------|--------|--------|
| `stg_customers.customer_id` | ✅ | Seed |
| `c.customer_id` | ✅ | DML ↑ produces it |
| `c.full_name` | ❌ | No production edge connects to customer_id |
| `c.segment` | ❌ | Same |
| `c.region` | ❌ | FILTER only, no production edge |

### Implementation

1. `dataflow_service.py`: `compute_field_lineage(Y, graph)` — BFS with 16 edge rules
2. `dataflow_service.py`: `filter_graph(graph, R)` — filter to lineage set
3. `dataflow.py`: add `lineage_mode` to `search_dataflow`

### Files

- `wiki/DATAFLOW_FORMAL_DEFINITION.md` — ✅ formal definition with 16 edge-type rules (done)
- `backend/app/services/dataflow_service.py` — `compute_field_lineage()`, `filter_graph()`
- `backend/app/routers/dataflow.py` — `lineage_mode` parameter