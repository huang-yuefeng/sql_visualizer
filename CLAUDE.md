# CLAUDE.md — SQL Data Flow Visualizer

> Auto-generated snapshot for AI-assisted development. Update after major refactors.

## Project Overview

A **SQL data flow debugger** with 3-panel React frontend and FastAPI Python backend.
Parses SQL scripts → extracts variables + dependencies → renders interactive
Cytoscape.js data flow graphs (L1 cross-script pipeline, L2 per-script detail).

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker `gps-sql-backend` on port 8000
- **Frontend**: React 18 + Vite + Cytoscape.js, served from `frontend/dist/`
- **Tests**: vitest (frontend, 70 passed), pytest (backend, 523 passed / 5 skipped in `backend/tests/`)
- **Version**: See `/VERSION` (currently 3.3.135)
- **Service IP**: `192.168.0.66:8000` (never use `localhost`)

## File Map (Key Source Files)

### Backend (`backend/app/`)

| File | Lines | Role |
|------|-------|------|
| `routers/dataflow.py` | 401 | `GET /api/workspace/{ws_id}/views/{view_id}/level1`, `GET .../level2?script=&filter=`, `POST .../search`, view CRUD, `GET .../scripts/{name}/highlight` |
| `routers/workspace.py` | 214 | `/api/workspace` CRUD (DELETE: 400 malformed / 404 missing / 200 deleted), scan, index, filter-config, export-config, autocomplete |
| `routers/analysis.py` | 73 | Legacy `/api/analyze`, `/api/scripts`, `/api/analyze_multi` |
| `services/filter_service.py` | 509 | **Filter logic** (R19): CSV parse → scopes → A∩B intersection → filter application + diagnostics (F6); shared `resolve_script` (R5, path-containment-checked); F3/F4/F5 (COL_NAME-only rows dropped + `ignored_rows` counters, case folding) |
| `services/l1_builder.py` | 920 | Cross-script L1 builder (production BFS → lineage_field_pairs → filter); M4-B degraded fallback (`degraded: true` + diagnostic); C2 single-cache-pass |
| `services/l2_builder.py` | 960 | Per-script L2 builder; C1 split into 13 named phases (`_build_edge_list`, `_simplify_dml_edges`, ...) — byte-identity-verified |
| `services/dataflow_service.py` | 398 | SearchView, view persistence (views.json, persists match_mode), edge style helpers |
| `services/folder_index_service.py` | 938 | Folder scanning, script indexing, **A1 schema-file classification** (`file_class: schema\|script`), **S4b cross-script schema auto-resolution** (scope-aware, owner-in-index, exact-name-first), resolution_stats aggregation, orphan report, index progress, `schema_evidence` in response |
| `services/cache_keys.py` | 15 | `GRAPH_CACHE_PREFIX = "graph_3_2_15"` (single source of truth) |
| `services/graph_service.py` | 318 | Cytoscape JSON builder, NODE_STYLES, EDGE_TYPE_STYLE/CATEGORY_MAP, table_fields/alias_map |
| `services/sql_range_finder.py` | 708 | SQL line-range mapping for edge→code highlighting |
| `services/logger.py` | 167 | SSE pipeline logger (ref-counted queue cleanup) |
| `extractor/variable_extractor_v2.py` | 1831 | Role-based Identifier walking + S1–S6 orphan resolution; **S4a auto-attribution** (`_finalize_schema_candidates`, R6 field==table collision guard), statement-anchored loc, dict-of-dicts script_schemas; C4a unified stats (`resolved`/`unresolved_count`/`coverage_pct`) |
| `extractor/dependency_graph.py` | 479 | VariableDefinition → VariableDependency (16 edge types) |
| `extractor/lineage.py` | 348 | `compute_field_lineage()`, `filter_relevant()` (R18) |
| `extractor/schema_inference.py` | 180 | `infer_table_schemas()` — 7-pass iterative stabilization |
| `models/variable.py` | 125 | VariableType enum (15 types), VariableDefinition |
| `models/sql_model.py` | 160 | Canonical taxonomy: node↔edge types mapped to SQL |

### Frontend (`frontend/src/`)

| File | Lines | Role |
|------|-------|------|
| `DataFlowApp.jsx` | 713 | Data Flow Debugger main component (search, view persistence, resolution report, `schema_evidence` state) |
| `App.jsx` | 857 | SQL Analysis (legacy single-script) |
| `components/DataFlowGraph.jsx` | 167 | Cytoscape renderer |
| `components/SqlPanel.jsx` | 332 | SQL display + syntax highlighting |
| `components/FilterPanel.jsx` | 329 | Filter upload UI + warning banner (R2), renders `ignored_rows` |
| `components/ResolutionReport.jsx` | 97 | Orphan resolution coverage badge + breakdown (R20) |
| `components/WorkspacePanel.jsx` | 75 | Workspace upload/scan/index UI |
| `utils/layoutCore.js` | 244 | Shared layout: `fieldPositionsForTable()`, `positionTableFields()`, `applyLayout()` |
| `utils/snakeLayout.js` | 107 | Snake/wrapping layout |
| `utils/elkLayout.js` | 239 | ELK layered layout |
| `utils/resolutionReport.js` | 93 | Stats normalization (prefers unified `unresolved_count`/`coverage_pct`) |
| `hooks/useCytoscapeGraph.js` | 154 | Cytoscape lifecycle: init, drag (recomputes from frozen offsets), layout dispatch |
| `config/layout.js` | 49 | Layout constants (single source of truth) |
| `api/client.js` | 164 | API client + `errorDetail()` (L12) |

## Architecture

```
SQL Text → sqlglot parse → variable_extractor_v2 → dependency_graph
    → graph_service (Cytoscape JSON) → FastAPI → React + Cytoscape.js
```

L1 (cross-script): `l1_builder.py` — scripts + tables + `reads_from`/`writes_to` edges, filtered by lineage BFS.
L2 (per-script): `l2_builder.py` — tables + fields + all 16 edge types within a single script.

## Key Design Decisions

1. **No compound Cytoscape nodes.** Fields use `_tableParent` + frozen relative offsets (`computeFieldRelPos()`). Layout algorithms only position tables/scripts; `applyLayout()` positions fields at `table.pos + offset`; drag recomputes from frozen offsets.
2. **Layout constants** live in `config/layout.js` only. No other file hardcodes sizes.
3. **16 edge types** with styles in `graph_service.py` (EDGE_TYPE_STYLE, CATEGORY_MAP).
4. **Lineage mode** (R18): `compute_field_lineage()` in `lineage.py` filters graph to only relevant field-level data flow.
5. **DO NOT USE `localhost`** — service runs at `192.168.0.66:8000`.
6. **Orphan resolution (R20)**: every column reference carries the table that owns it (S1 plain_alias, S2 expr_alias/CTE/derived outputs, S3 nearest single-table scope, S4 schema unique-owner, S5 sys sentinel, S6 pseudocolumns). Never guess — ambiguous columns stay unresolved and are reported via the ORPHAN RESOLUTION REPORT. **S4 live (Phase 2, v3.3.133)**: extractor auto-attributes unique-visible-owner candidates (S4a), index re-tests residuals scope-aware (S4b). **A1 (v3.3.134)**: `.ddl`/`.schema` files and pure-DDL `.sql` files classify as schema files — they contribute schema evidence to `m_ws` but never pipeline counts/L1/L2/filter scopes. Coverage sweep 2026-08-06 (combined tpcds+tpcds_qualified, 207 scripts): **99.9%, 8 residual orphans** (baseline 95.8%/291; M4 denominator fix means numbers aren't comparable with the interim 96.6%).
7. **Filter semantics (R19)**: two-file filter = A∩B intersection; blank COL_NAME row = table unconstrained (all fields kept); `resolve_script` enforces path containment (H1); COL_NAME-only rows dropped by design and counted in `ignored_rows` (F3).
8. **M4-B**: L1's degraded fallback is visible — response carries `degraded: true` + an L1 GRAPH DEGRADED diagnostic box.
9. **Diagnostics, never fixes**: when source files are wrong/incomplete, the tool reports in the diagnostic panel — it never edits user files, annotates, or works around them (A1 report-only design).

## Running Tests

```bash
# Frontend
cd frontend && npm test

# Backend
docker exec -w /app/backend gps-sql-backend python3 -m pytest tests/ -q

# Full smoke test
curl -s http://192.168.0.66:8000/api/health
```

## Docker Commands (no sudo — user huangyf is in docker group)

```bash
docker restart gps-sql-backend                    # restart backend
docker compose -f docker-compose.yml up -d        # rebuild + start
curl -s http://192.168.0.66:8000/api/health       # health check
./target_deploy.sh   # target-machine deploy: version-guarded (RELEASE.txt manifest + origin check), logs to target_deploy.log
```
