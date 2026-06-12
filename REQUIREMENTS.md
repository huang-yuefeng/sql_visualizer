# Requirements Implemented — v2.4.0

> Current state of all features, fixes, and improvements.

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
