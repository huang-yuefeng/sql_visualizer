# CLAUDE.md — SQL Data Flow Visualizer

> Auto-generated snapshot for AI-assisted development. Update after major refactors.

## Project Overview

A **SQL data flow debugger** with 3-panel React frontend and FastAPI Python backend.
Parses SQL scripts → extracts variables + dependencies → renders interactive
Cytoscape.js data flow graphs (L1 cross-script pipeline, L2 per-script detail).

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker `gps-sql-backend` on port 8000
- **Frontend**: React 18 + Vite + Cytoscape.js, served from `frontend/dist/`
- **Tests**: vitest (frontend), pytest (backend, 254+ tests in `backend/tests/`)
- **Version**: See `/VERSION` (currently 3.3.106)
- **Service IP**: `192.168.0.66:8000` (never use `localhost`)

## File Map (Key Source Files)

### Backend (`backend/app/`)

| File | Lines | Role |
|------|-------|------|
| `routers/dataflow.py` | 352 | `/api/search`, `/api/views/{id}/l1`, `/api/views/{id}/l2` |
| `routers/workspace.py` | 336 | `/api/workspace` upload, index, filter config |
| `services/dataflow_service.py` | 1989 | **L1/L2 builders** + SearchView + edge style helpers (oversized — needs split) |
| `services/graph_service.py` | 197 | Cytoscape JSON builder, NODE_STYLES, edge helpers (EDGE_TYPE_STYLE, CATEGORY_MAP) |
| `services/sql_range_finder.py` | 663 | SQL line-range mapping for edge→code highlighting |
| `services/logger.py` | — | SSE-based pipeline logger + `pipeline_profile()` |
| `extractor/variable_extractor_v2.py` | 885 | SQL parse → VariableDefinition (15 types) |
| `extractor/dependency_graph.py` | 479 | VariableDefinition → VariableDependency (13 edge types) |
| `extractor/lineage.py` | 282 | `compute_field_lineage()`, `filter_relevant()` (R18) |
| `extractor/schema_inference.py` | 180 | `infer_table_schemas()` — 7-pass iterative stabilization |

### Frontend (`frontend/src/`)

| File | Lines | Role |
|------|-------|------|
| `AppShell.jsx` | — | Tab router (SQL Analysis / Data Flow Debugger) |
| `DataFlowApp.jsx` | 591 | Data Flow Debugger main component |
| `App.jsx` | 857 | SQL Analysis (legacy single-script) |
| `components/DataFlowGraph.jsx` | 180 | Cytoscape renderer |
| `components/SqlPanel.jsx` | 326 | SQL display + syntax highlighting |
| `utils/layoutCore.js` | 206 | Shared layout: `tableHeight()`, `applyLayout()`, `stripFieldParents()` |
| `utils/snakeLayout.js` | 107 | Snake/wrapping layout: `computeSnakePositions()`, `runSnakeLayout()` |
| `utils/elkLayout.js` | 239 | ELK layered layout |
| `hooks/useCytoscapeGraph.js` | 158 | Cytoscape lifecycle: init, drag, layout dispatch |
| `config/layout.js` | 49 | Layout constants (single source of truth) |

## Architecture

```
SQL Text → sqlglot parse → variable_extractor_v2 → dependency_graph
    → graph_service (Cytoscape JSON) → FastAPI → React + Cytoscape.js
```

L1 (cross-script): `_build_l1_graph()` in `dataflow_service.py` — scripts + tables + `reads_from`/`writes_to` edges.
L2 (per-script): `_build_l2_graph()` — tables + fields + all 16 edge types within a single script.

## Key Design Decisions

1. **No compound Cytoscape nodes.** Fields use `_tableParent` + frozen relative offsets (`computeFieldRelPos()`). Layout algorithms only position tables/scripts; `applyLayout()` positions fields at `table.pos + offset`.
2. **Layout constants** live in `config/layout.js` only. No other file hardcodes sizes.
3. **16 edge types** with styles in `graph_service.py` (EDGE_TYPE_STYLE, CATEGORY_MAP).
4. **Lineage mode** (R18): `compute_field_lineage()` in `lineage.py` filters graph to only relevant field-level data flow.
5. **DO NOT USE `localhost`** — service runs at `192.168.0.66:8000`.

## Running Tests

```bash
# Frontend
cd frontend && npm test

# Backend
cd backend && python3 -m pytest tests/ -v

# Full smoke test
curl -s http://192.168.0.66:8000/api/health
```

## Docker Commands (no sudo — user huangyf is in docker group)

```bash
docker restart gps-sql-backend                    # restart backend
docker compose -f docker-compose.yml up -d        # rebuild + start
curl -s http://192.168.0.66:8000/api/health       # health check
```
