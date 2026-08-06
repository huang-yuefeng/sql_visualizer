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

> **Priority:** P2 | **Date:** 2026-07-23

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

> **Priority:** P2 | **Date:** 2026-07-23

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

> **Priority:** P2 | **Date:** 2026-07-27

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

> **Priority:** P2 | **Date:** 2026-07-27

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

> **Priority:** P2 | **Date:** 2026-07-28

**Description:** When a user searches for a specific field (`table=T, field=Y`), filter both L1 and L2 graphs to show only nodes and edges on the data flow path of field Y. UI/UX unchanged — same graph, same L1/L2 interactions, fewer elements.

### Formal Definition

See [`wiki/DATAFLOW_FORMAL_DEFINITION.md`](../wiki/DATAFLOW_FORMAL_DEFINITION.md) — Field-Level Data Flow section for the complete 16 edge-type rule table, Lineage Set R definition, worked example, and design framework; and the **Table Type Invariants** section for field synchronization (alias ↔ original) and output table flow completion rules.

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
│   → post-cleanup: remove tables with 0 field children    │
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
| L1 graph | All scripts + fields for table T | Only fields in Y's lineage chain (via `compute_field_lineage`, not name matching) |
| L2 graph | All fields in table T | Only Y's upstream sources + downstream targets |
| UI/UX | Click L1→L2, click edge→SQL | Unchanged |
| Unrelated same-table fields | Shown | Hidden |
| Unrelated same-name fields | Shown (name match) | **Hidden** (not in lineage) |

### Lineage vs Name Matching

**Name matching is not lineage.** Two fields with the same name (e.g., `customer_id` in `stg_customers` and `stg_orders`) are NOT automatically in each other's lineage. Lineage follows the data flow of the field's **value** — which table/expression produced it, which edges carried it.

`compute_field_lineage` in `lineage.py` is the single source of truth for lineage computation. Both L1 and L2 must use it. L1 must NOT use name-based filtering as a substitute.

### Example 1: Same-script fields

`INSERT INTO stg_customers SELECT c.customer_id, c.full_name, c.segment FROM crm_customers c WHERE c.region='NA'`
**Query:** `table=stg_customers, field=customer_id`

| Field | Shown? | Reason |
|-------|--------|--------|
| `stg_customers.customer_id` | ✅ | Seed |
| `c.customer_id` | ✅ | DML ↑ produces it |
| `c.full_name` | ❌ | No production edge connects to customer_id |
| `c.segment` | ❌ | Same |
| `c.region` | ❌ | FILTER only, no production edge |

### Example 2: Cross-branch same-name fields

**Query:** `stg_customers.customer_id` in multi_workflow
```
crm_customers.customer_id → step2 → stg_customers.customer_id → step3(JOIN)
raw_orders.customer_id    → step1 → stg_orders.customer_id    → same JOIN
```

| Field | Shown? | Reason |
|-------|--------|--------|
| `stg_customers.customer_id` | ✅ | Seed |
| `crm_customers.customer_id` | ✅ | DML ↑ via step2 |
| `stg_orders.customer_id` | ❌ | JOIN only — not in production chain for stg_customers |
| `raw_orders.customer_id` | ❌ | Produces stg_orders.customer_id, different branch |

### Algorithm

```
Step 1: Construct initial R   — find table node, find field via SCHEMA, validate both exist
Step 2: Expand R by BFS        — walk edges with type-specific rules, R stabilizes
Step 3: Filter graph           — keep nodes/edges in R, drop rest (no name-based post-filter)
Step 4: Wire into pipeline     — create_search accepts lineage_mode, calls filter_relevant

Step 5 (L1 only): Cross-script constrained union
    — For each script in the pipeline, compute Rᵢ via compute_field_lineage
    — R₁ = ⋃ Rᵢ, constrained: fields excluded by conditional edges (JOIN/FILTER)
      in ANY script are excluded from R₁
Step 6 (L1+L2): Post-filter cleanup (R18.1)
    — Remove tables with 0 field children (except terminal marker)
    — Keep immediate downstream table as terminal marker (empty)
    — Keep scripts connected to terminal marker (for manual L2 verification)
    — Keep edges: terminal marker ↔ scripts (incoming + outgoing)
    — Remove further downstream tables (not connected to terminal marker scripts)
```

**Key design constraint:** Both L1 and L2 use `compute_field_lineage` as the single lineage engine. L1 does NOT use name matching. L1 is the constrained union of per-script L2 results, not an independent filter.

### R18.1 — Empty Table Cleanup After Lineage Filtering

> **Priority:** P2 | **Date:** 2026-07-30

**Description:** After lineage filtering removes non-lineage field nodes, some table nodes may have **0 remaining field children**. This happens when the queried field's value does NOT propagate into a downstream table — e.g., `customer_id` is used only in a JOIN condition (`ON so.customer_id = sc.customer_id`) but is not INSERTed into the output table. The data flow of the field's value terminates at the last table that carries it.

Downstream tables without the queried field are removed — **except for the immediate termination point**: keep the FIRST downstream table that lacks the field as a **terminal marker** (empty, 0 field children). Scripts connected to the terminal marker are **kept with their edges** — users can open each script's L2 view to manually verify that the queried field is not used in data-producing operations (e.g., only in JOIN, not INSERT). All further downstream tables (outputs of terminal-connected scripts) are removed.

**Design principle:** Lineage follows **data flow of the field's value**, not structural table dependency. The terminal marker shows where automatic lineage tracing stops. Connected scripts are preserved for manual inspection — the user can click through to confirm the field is absent from each script's data flow, rather than trusting the algorithm blindly.

**What changes:**

| | Current | Desired |
|---|---|---|
| Immediate empty table | Shown (empty) | **Kept** (terminal marker) + edge from producer script |
| Scripts connected to terminal marker | Shown | **Kept** — users can open L2 to verify field absence |
| Outgoing edges to terminal-connected scripts | Shown | **Kept** — shows which scripts to inspect |
| Further downstream tables (outputs of terminal scripts) | Shown (empty) | **Removed** — not in lineage chain |
| Disconnected scripts (no tables after cleanup) | Shown | **Removed** |

**Example** (`stg_customers.customer_id` in multi_workflow):

```
step3(JOIN) ──writes_to──> analytics_orders  ← KEPT (empty, terminal marker)
                            analytics_orders ──reads_from──> step4  ← KEPT (inspect in L2)
                            analytics_orders ──reads_from──> step5  ← KEPT (inspect in L2)
step4(AGGREGATE) ──writes_to──> daily_summary  ← REMOVED (not in lineage chain)
step5(SELECT) ──writes_to──> report            ← REMOVED (not in lineage chain)
```

`analytics_orders` stays (empty) to show: "step3 processes `customer_id`, but `customer_id` doesn't reach `analytics_orders`'s columns." step4 and step5 stay connected — the user can double-click them to open L2 and manually verify that `customer_id` is absent from their INSERT/SELECT operations. `daily_summary` and `report` (outputs of step4/step5) are removed.

**Implementation:**

- **L1** (`_filter_l1_by_lineage`): after identifying `terminal_table_ids`:
  1. Keep all edges involving the terminal marker (do NOT remove outgoing)
  2. Remove further downstream tables (outputs of terminal-connected scripts) not in `field_parent_ids` or `terminal_table_ids`
  3. Remove scripts with no remaining table connections
- **L2**: terminal-connected scripts are fully interactive (openable, SQL highlights work)

**Files:**
- `backend/app/services/dataflow_service.py:336-377` — L1 cleanup
- `backend/app/services/dataflow_service.py:1681-1684` — L2 cleanup

### Acceptance Criteria

- [ ] `infer_table_schemas()` runs after extraction for every script
- [ ] `table_schemas` dict maps every table to its inferred columns
- [ ] Seed lookup uses table_schemas (O(1)) instead of fuzzy label matching
- [ ] `lineage_mode=true` returns fewer fields than `lineage_mode=false` for the same query
- [ ] Field `customer_id` in `stg_customers` excludes `full_name`, `segment`, `region`
- [ ] Field not in table_schemas → error "field not found in table"
- [ ] Works for SELECT-only, INSERT...SELECT, UPDATE, MERGE, CTAS
- [ ] Works with multi-hop chains (ALIAS → TABLE_FLOW → DML)
- [ ] L1 graph shows only lineage fields when lineage_mode=true
- [ ] L2 graph shows only lineage fields when viewing per-script

### Test Plan

- [ ] Unit test: `infer_table_schemas()` for each SQL operation type (INSERT, SELECT, JOIN, UNION, CTE)
- [ ] Unit test: multi-hop chain (ALIAS → TABLE_FLOW → DML) produces correct schemas
- [ ] Unit test: iterative stabilization — verify passes repeat until stable
- [ ] Unit test: seed lookup validates table + field existence
- [ ] Integration test: `lineage_mode=true` on step2 excludes `full_name`/`segment`/`region`
- [ ] Integration test: `lineage_mode=false` still shows all fields
- [ ] Regression test: existing multi_workflow tests still pass

### Files

- `wiki/DATAFLOW_FORMAL_DEFINITION.md` — ✅ formal definition (done)
- `wiki/SOLUTION_DESIGN.md` — ✅ schema inference + lineage design (done)
- `backend/app/extractor/variable_extractor_v2.py` — `infer_table_schemas()`
- `backend/app/services/dataflow_service.py` — `compute_field_lineage()`, `filter_relevant()`
- `backend/app/routers/dataflow.py` — `lineage_mode` parameter
- `backend/tests/test_field_lineage.py` — new test file
---

## R19 — Two-File Filter Intersection Semantics

> **Priority:** P2 | **Date:** 2026-08-03 | **Status:** Design pending review

**Description:** When the user uploads BOTH filter CSV files (script_table.csv + table_col.csv), the effective table scope must be the **intersection** of the tables in both files — not the union.

### Problem

Current behavior (`workspace.py:upload_filter_config`): `allowed_tables` is the **union** of `script_table.csv` tables (file 1) and `table_col.csv` tables (file 2). Tables present only in `table_col.csv` silently **expand** the filter scope beyond what `script_table.csv` defines; the code only emits a diagnostic warning ("table_col.csv added N new tables not in script_table scope"). This contradicts the user's intent: `table_col.csv` is a column-documentation file, not a scope-expansion file.

### Requirement

Given:
- `A` = tables in `script_table.csv` (file 1)
- `B` = tables in `table_col.csv` (file 2)

When both files are uploaded:
1. **Effective table scope = A ∩ B.** Tables present only in `table_col.csv` (B − A) are **ignored**. Tables present only in `script_table.csv` (A − B) are also excluded from the effective scope (symmetric interpretation — flag for reviewer confirmation).
2. **Fields**: only columns whose table ∈ (A ∩ B) are kept in the filtered field index. Columns documented in `table_col.csv` for tables outside the intersection are dropped.
3. **Scripts**: script scope continues to come from `script_table.csv` only (unchanged).
4. **Single-file uploads** (either file alone): behavior unchanged — file 1 alone scopes scripts+tables; file 2 alone scopes tables+columns.
5. **Neither file**: clears the filter (unchanged).
6. The R16 diagnostic must report the intersection decision: number of tables ignored from `table_col.csv` (B − A) and the final effective table count.

### Acceptance criteria

- [ ] Table in both CSVs → present in filtered index
- [ ] Table only in `table_col.csv` → absent from filtered index (regardless of its columns)
- [ ] Column of an excluded table in `table_col.csv` → absent from filtered field index
- [ ] Column of an intersection table in `table_col.csv` → present in filtered field index
- [ ] File-1-only upload → unchanged (tables = A)
- [ ] File-2-only upload → unchanged (tables = B, columns = B's)
- [ ] No files → filter cleared
- [ ] R16 diagnostic shows ignored-table count
- [ ] Existing tests still pass (334 + new)

---

### Note (R1 — 2026-08-06): blank COL_NAME semantics (decision made)

A `table_col.csv` row with **`TABLE_NAME` set but blank/empty `COL_NAME`** means the table has **no column constraint**: all of its indexed fields pass the field filter. This restores pre-F2 behavior and matches the "single-file uploads unchanged" principle — a table-only file filters tables, not fields.

- If a table appears in **both** a COL_NAME row and a blank-COL_NAME row, the blank row wins: the table is unconstrained (the column rows' union plus everything else of that table).
- Unconstrained status only applies within the effective table scope — with both files, a blank row for a table outside A∩B does **not** let that table's fields leak into the filtered field index.
- Implemented in `backend/app/services/filter_service.py` (F6 extraction) with regression tests in `backend/tests/test_filter_config.py` (`TestR1BlankColName`).

## R20 — Orphan Resolution Coverage Report (extraction-phase resolution feedback)

> **Priority:** P1 | **Date:** 2026-08-04 | **Status:** Design done (SOLUTION_DESIGN.md "Orphan Resolution")

**Description:** All orphan fields (columns with no table attribution) are resolved automatically **in the extraction phase** — the solution must understand any SQL, never require the SQL to be mended. After all scripts are parsed, the diagnostic reports the resolution **coverage** (fixed vs total) and lists the **unresolved** orphans with their SQL segments, so humans can confirm and discover bad cases (extraction gaps, new SQL patterns) in real usage.

### Requirement

1. **Extraction-phase resolution** (per script): unqualified columns and alias columns are attributed to their tables by the extractor:
   - S1 plain alias inheritance (`t.col AS x` → inherits `t.col`'s table)
   - S2 expression-alias output attribution (CTE output / ⟐ output / INSERT target via Bug 41)
   - S3 nearest-scope resolution (bare column, exactly 1 physical table in the nearest SELECT scope)
   - S4 schema-based resolution (bare column, ≥2 tables — resolved at index time after `infer_table_schemas`, exact/word-boundary match, unique owner only)
   - S5 system tables (INFORMATION_SCHEMA) excluded/marked — never a defect
   - S6 pseudocolumns/trigger vars (LEVEL, new, old) marked expected — never counted as unresolved defects
2. **Coverage data** (after all scripts parsed, at index time): the diagnostic reports
   - total column variables, resolved count, coverage % (resolved / total)
   - per-strategy resolution counts (S1–S4)
3. **Unresolved orphans reported** with their SQL segments (field, script, lines mentioning the field) — the human-visible residual. Unresolved = fields still with no table after S1–S6, excluding S5/S6 marked-expected entries.
4. The coverage data is a **regression meter**: a coverage drop after an extractor change signals a new bad case; usage of the system surfaces more bad cases for the extraction to learn from.

### Acceptance criteria

- [ ] Coverage % + per-strategy counts appear in the index-time diagnostic
- [ ] Unresolved orphans listed with field + script + SQL lines (existing ORPHAN FIELD REPORT format)
- [ ] S5/S6 entries excluded from the unresolved count (marked expected)
- [ ] Coverage is computed AFTER all scripts are parsed (post-extraction/index)
- [ ] Existing samples: coverage ≥ 90% after S1–S6 (per the verified strategy estimates)
- [ ] Existing tests still pass (355+)

## R21 — Remove L1 Script-Info Popup (requirement change)

> **Priority:** P2 | **Date:** 2026-08-06 | **Status:** Implemented (v3.3.135)

**Description:** Remove the bottom-right popup box on the L1 graph that shows the
single-clicked script's label plus "Variables:", "Inputs:", and "Outputs:" lists.
This reverses one UI element of the original L1 design; the underlying data
(total_variables / input_tables / output_tables) remains on the script nodes and
in the L2 view — only the overlay popup goes away.

### Problem

The popup (`.script-info-popup`, absolutely positioned bottom-right,
`max-width: 250px`, **no `max-height`**) is fed by a single-click `onTap` handler
on L1 `script_node`s. For scripts with long input/output table lists the box
grows until it covers most of the L1 panel, hiding the graph the user is trying
to navigate. It can only be dismissed with the small × button and reappears on
every single click; its information duplicates what the user already gets by
double-clicking into L2.

### Requirement

1. **Remove the popup and its data plumbing** — 3 files, deletions only:
   - `frontend/src/components/DataFlowGraph.jsx`: drop the
     `scriptInfo`/`onScriptInfoChange` props, the `onTap` handler that fed the
     popup, and the popup JSX block.
   - `frontend/src/DataFlowApp.jsx`: drop the `scriptInfo` state + its setter
     call sites and the props at both `<DataFlowGraph>` render sites.
   - `frontend/src/styles/app.css`: drop `.script-info-popup` + `.sip-header`.
2. **Single-click on an L1 script node does nothing** (no popup, no nav).
3. **Everything else unchanged**: double-click-to-open-L2 (`onDblTap`), edge
   hover tooltip, edge click, hover cursor, layout toggles, graph canvas sizing.

### Acceptance criteria

- [ ] Zero references to `scriptInfo` / `onScriptInfoChange` / `script-info-popup` / `sip-header` in `frontend/src` (excluding `*.bak` backup files, removed from tracking in R21)
- [ ] Single-click on L1 script node → no UI change
- [ ] Double-click on L1 script node → L2 still opens
- [ ] Edge hover tooltip, edge click, hover cursor still work
- [ ] Frontend tests pass (70) and production build succeeds
- [ ] No CSS rule referencing the popup classes remains in `app.css`

## R22 — L2 table dedup + data-flow-participation search (requirement change, 2026-08-06)

> **Priority:** P1 | **Date:** 2026-08-06 | **Status:** Implemented (v3.3.136)

**Description:** Fixes for three user-reported issues on the repro script
`BDM_ACC_LOAN_INFO_SUP_M.sql` (OCR-reconstructed from user screenshots,
preserved as a regression case in `samples/sql_sample_v1/`), plus the
genuinely-open items from the 2026-08-06 code review.

### Problem

1. **Issue a — duplicate table nodes.** One physical table used in multiple
   SQL contexts (CTE FROM, JOIN alias, subquery) rendered as N L2 nodes — the
   repro script showed 4× `bdm_acc_loan_info` (64 table nodes for ~15 tables).
   Cause: `_classify_compound_nodes` keys compound table nodes by the
   context-scoped variable id; the extractor emits one TABLE variable per
   scope.
2. **Issue b — false search match.** Searching `bdm_acc_loan_info.ABROAD_LOAD_
   PURPOSE` matched the script although the field is never queried by it
   (`match_mode: "fallback"` padded in all table-referencing scripts), making
   the L1 include scripts/tables not in the searched field's data flow.
3. **Issue c — misleading L2 skeleton.** With the absent search field, the L2
   relevance filter degraded to a 5-node / 0-edge table-only skeleton with no
   explanation anywhere.
4. **Code-review items M12–M15, L16, R21-1/2** — S4b "first script wins",
   context-blind cache attribution, stale graph caches, unconditional schema
   counter, `_statement_anchor` string-token miss, tracked `.bak` hygiene.

### Requirement

1. **One L2 table node per physical table.** Non-alias `table`/`view` nodes
   are merged by label into a single compound node (first occurrence is the
   keeper); the data flow may pass through it multiple times — edges from
   every context re-point to the keeper; field nodes dedup by (parent, name);
   search-target highlights map through the merge. Aliases/subqueries/CTEs
   keep per-context nodes. The merge runs per request on the cached graph —
   no extractor/cache-format changes. `_build_l2_graph` returns
   `search_matched: bool` (False only when a relevance filter was requested
   and no target/direct seed matched).
2. **Search matches only real data flow.** A `table.field` search matches a
   script only if that field is queried by it. No fallback padding: when no
   script queries the field → `match_mode: "no_matches"` + an accurate
   message ("Field X is not queried by any script in this workspace — no
   data flow exists for it") + empty L1. The R17 diagnostic distinguishes
   base-index-absent (never blames the filter CSVs) from filter-excluded
   (keeps the "add to table_col.csv" hint). The level1 endpoint applies the
   same R18 lineage filter as the search-time path.
3. **L2 "not in data flow" state.** When the view's search field is absent
   from the script, the level2 response carries `search_matched: false` +
   a message and returns the FULL unfiltered graph; the frontend renders a
   banner ("Script X is not in the data flow of T.F — the field is not
   queried in this script") above the graph. Absence of `search_matched`
   means matched.
4. **Code-review fixes.** M12: two-phase S4b (plan → conflict-detect →
   apply), cross-owner conflicts marked `ambiguous_fields`, revoked from
   prior owners, returned to UNRESOLVED, counted in
   `resolution_stats["ambiguous"]`. M13: S4b cache attribution gated on the
   variable's context ∈ candidate contexts. M14: `GRAPH_CACHE_PREFIX`
   bumped to `graph_3_2_16`. M15: `by_strategy["schema"]` incremented only
   when ≥1 var actually attributed. L16: `_statement_anchor` uses a
   type-aware `_is_as_keyword` (never matches a STRING literal as the anchor
   `as`). R21-1/2: all tracked `.bak*` files removed from git, `.gitignore`
   covers `*.bak.*`, requirement wording corrected.
5. **Regression fixture.** The OCR-reconstructed script is committed under
   `samples/sql_sample_v1/` (with README provenance) and pinned by
   `backend/tests/test_dataflow/test_sample_v1_repro.py` (8 tests: extractor
   invariants 344 vars / 1102 deps, 4-context same-table signature, field
   `ABROAD_LOAD_PURPOSE` deliberately absent).

### Acceptance criteria

- [ ] Repro script unfiltered L2: `bdm_acc_loan_info` = 1 node (was 4); total
      table nodes 54 (was 64); zero dangling edge endpoints; zero leaked
      `merged_original_ids`
- [ ] Search `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE` → `no_matches` + message;
      control search (`lending_ref`) still `exact`
- [ ] L2 with that view → `search_matched: false` + message + full graph
      (378 nodes / 147 edges); field-present view → no `search_matched` key
- [ ] L1 no-match banner shows the message; L2 not-in-flow banner shows it too
      (same `.no-match-banner` style)
- [ ] M12: two scripts, same field, different owners → ambiguous + reported;
      same owner → still resolved. M13: attribution respects context.
      M15: counter stays 0 when nothing attributed (mutation-verified)
- [ ] L16: `SELECT 'as' AS c, a FROM t1;` before a real statement → anchor on
      the real line (test verified red before, green after)
- [ ] `git ls-files | grep -i '\.bak'` → empty; `git check-ignore x.bak.*` → ignored
- [ ] Backend 556 passed / 5 skipped; frontend 70 passed + build OK; health
      `{"status":"ok","version":"3.3.136"}`

## R23 — Remove browser auto-restore of last workspace (requirement change)

> **Priority:** P2 | **Date:** 2026-08-06 | **Status:** Implemented (v3.3.137)

**Description:** Opening the service always starts with NO workspace selected —
the user picks or creates one from the upload panel. The app no longer reads
localStorage to restore the last-used workspace + view after a page reload;
the R3 search-view persistence feature (added so a reload resumes the last
search) is removed entirely, including its dead helper code and the one-time
purge of its localStorage key.

### Problem

User feedback: "When I open the service, there is a previous workspace. why?"
On mount, `DataFlowApp` read saved state from localStorage
(`df_last_search_view`, written at every search): it re-fetched the saved
workspace (`getWorkspaceInfo`), re-scanned (`scanWorkspace`), re-indexed
(`indexWorkspace`), re-listed views (`listViews`), and re-opened the saved
view with its cached L1 graph — silently re-entering a workspace the user
never asked to open. The behavior surprises users, implies state persisted
without their intent, and races an upload started during the restore (the
R3 `uploadTokenRef` guard).

### Requirement

1. **Clean start on load.** Opening the app always starts with no workspace
   selected and the empty state ("Upload a folder to get started"); the user
   picks or creates a workspace themselves. Nothing reads localStorage to
   open a workspace or view on page load.
2. **Remove the restore feature entirely.** Delete the mount-time restore
   effect (the `saved.wsId` block calling `getWorkspaceInfo` /
   `scanWorkspace` / `indexWorkspace` / `listViews`), the localStorage save
   side (`LAST_SEARCH_KEY` / `loadLastSearch` / `saveLastSearch` /
   `clearLastSearch` and their call sites in `handleSearch` /
   `handleUpload`), and `mergeRestoredViews` (`restoreViews.js`) — its only
   call site was the mount restore. Remove the now-unused API wrappers
   `getWorkspaceInfo` and `scanWorkspace` from `client.js`, and the R3
   upload-race guard (`uploadTokenRef`).
3. **One-time key purge.** On mount the app removes `df_last_search_view`
   from localStorage, so saved state from older sessions can never resurface
   (e.g. after a revert). Other localStorage keys (`theme`,
   `df_search_history`, `df_pinned_searches`) are untouched.
4. **Frontend-only.** Backend untouched — workspaces/views remain server-side
   state; only the auto-restore of them on load is gone.

### Acceptance criteria

- [ ] Opening the app → empty state, no workspace selected, no network calls
      to `getWorkspaceInfo` / `scanWorkspace` / `indexWorkspace` / `listViews`
      on mount
- [ ] Zero references to `LAST_SEARCH_KEY` / `loadLastSearch` /
      `saveLastSearch` / `clearLastSearch` / `mergeRestoredViews` /
      `restoreViews` in `frontend/src`
- [ ] `restoreViews.js` + `restoreViews.test.js` deleted; `uploadTokenRef`
      gone from `DataFlowApp.jsx`
- [ ] `df_last_search_view` removed from localStorage on mount
- [ ] Upload / scan / index / search / view tree / L2 still work unchanged
- [ ] Frontend tests pass (64) and production build succeeds

## R24 — Single-script folders show their script in L1 (requirement change)

> **Priority:** P1 | **Date:** 2026-08-06 | **Status:** Implemented (v3.3.137)

**Description:** A workspace containing exactly one script must still show
that script node in L1, and double-clicking it must open L2 — identical to
multi-script workspaces. Verified with `samples/sql_sample_v1/`
(`BDM_ACC_LOAN_INFO_SUP_M.sql`), the user's single-script repro folder.

### Problem

User feedback: "when there is only one script in the folder, we should show
it in L1, when clicking on script there should be L2. I am testing
sql_sample_v1." A single-script workspace search returned a **0-node L1**:
`_build_l1_graph`'s single-script shortcut returned only the bare script
node (no tables, no edges, no `lineage_field_pairs`), and
`_filter_l1_by_lineage`'s R18.1 cleanup then pruned that script as
"disconnected" (0 remaining table edges) — nothing was left to double-click
into L2. Both the search response and the level1 endpoint produced the
0-node graph, and the persisted `l1_graph_cache` in `views.json` stored it.

### Requirement

1. **Script node always present.** For a matched search in a single-script
   workspace (and for the level1 rebuild path of such a view), L1 must
   contain the script node — with its flow tables when the lineage filter
   keeps them. The R18.1 "remove disconnected scripts" rule may never prune
   the only script of a 1-script graph: the search already established it is
   in the searched field's flow (`match_mode` exact/expanded). Multi-script
   R18.1 pruning is unchanged.
2. **Full pipeline shape, not a bare node.** `_build_l1_graph` analyzes the
   one script inline (`analyze_multiple_scripts` refuses <2 scripts) and
   feeds the same `all_scripts` shape downstream, so L1 gets tables,
   `reads_from`/`writes_to` edges and lineage field children — exactly like
   the multi-script path (previously the shortcut skipped the entire
   pipeline).
3. **Click opens L2.** The script node carries `script_name`; the existing
   frontend `onDblTap` → `handleOpenL2` flow opens L2 unchanged (no
   frontend change required).
4. **R22 no_matches interaction (unchanged by design).** A search whose
   field is not queried by any script in the workspace still returns
   `match_mode: "no_matches"` + the accurate message + an EMPTY L1, in a
   single-script workspace exactly as in any other — the banner + empty
   graph for no_matches is intentional and untouched. Only a *matching*
   search in a single-script workspace shows the script node.

### Acceptance criteria

- [ ] Single-script workspace + matching search → L1 contains the script
      node (with its flow tables); node count > 0
- [ ] level1 endpoint for that view → same node set, script node present
- [ ] Double-click on the L1 script node → L2 opens (level2 works,
      `search_matched` absent = matched)
- [ ] Single-script workspace + no_matches search → still `no_matches` +
      message + empty L1 (R22 preserved)
- [ ] Multi-script R18.1 disconnected-script pruning unchanged (guard is
      1-script-only)
- [ ] New searches persist a non-empty `l1_graph_cache` in `views.json`
- [ ] Backend scoped tests pass (8 new R24 tests); live verification:
      fresh single-script workspace upload → search → L1 shows the script
      node
