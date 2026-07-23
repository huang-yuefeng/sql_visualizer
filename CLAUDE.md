# SQL Data Flow Visualizer — AI Context Guide

## Project Overview
Online web service for debugging SQL scripts via data flow visualization — extracts variables, builds dependency graphs, and renders interactive Cytoscape.js visualizations with compound nodes.

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker-based
- **Frontend**: React + Vite + Cytoscape.js + ELK.js
- **Service**: `http://192.168.0.66:8000` (container: `gps-sql-backend`)
- **Version**: See `/VERSION` file
- **Tests**: `docker exec gps-sql-backend python3 -m pytest tests/ -v`

## Module Map (current v3.3)

### Backend — Core Services
| File | Lines | What it contains |
|------|-------|-----------------|
| `backend/app/services/dataflow_service.py` | 1968 | L1/L2 graph builder, edge type system (16 types), DML routing, variable extraction |
| `backend/app/services/sql_range_finder.py` | 663 | SQL line-level extraction: `find_sql_range()`, `partition_edge_ranges()`, keyword/alias/label locators |
| `backend/app/services/folder_index_service.py` | 181 | Folder scanning, script indexing, autocomplete for table/field |
| `backend/app/services/graph_service.py` | 145 | Cytoscape JSON builder, node styles, edge colors |

### Backend — API Layer
| File | Lines | What it contains |
|------|-------|-----------------|
| `backend/app/routers/dataflow.py` | 296 | POST `/workspace/{id}/search`, GET `/views/{vid}/level1`, GET `/views/{vid}/level2` |
| `backend/app/routers/workspace.py` | 277 | Workspace CRUD, folder upload (`/workspace` POST), filter config, export config |
| `backend/app/routers/analysis.py` | 80 | POST `/analyze`, GET `/scripts`, POST `/analyze_multi` |
| `backend/app/routers/graph.py` | 40 | GET `/graph`, POST `/io_graph` |
| `backend/app/main.py` | 50 | FastAPI app initialization |

### Backend — Extraction & Models
| File | What it contains |
|------|-----------------|
| `backend/app/extractor/variable_extractor_v2.py` | Role-based Identifier walking — the core extractor |
| `backend/app/extractor/dependency_graph.py` | 12-phase edge creation algorithm |
| `backend/app/models/variable.py` | VariableType enum (15 types), VariableDefinition |
| `backend/app/models/sql_model.py` | Canonical taxonomy: node↔edge types mapped to SQL |

### Frontend — Visualization
| File | Lines | What it contains |
|------|-------|-----------------|
| `frontend/src/pages/DataFlowDebugger.jsx` | ~550 | Main debugger page: L1 navigation panel, L2 graph, SQL panel, search |
| `frontend/src/utils/layoutCore.js` | 206 | Shared layout: `computeFieldRelPos()`, `computeTableInfo()`, `applyLayout()` |
| `frontend/src/utils/elkLayout.js` | 239 | ELK.js layered layout ("Pipeline" mode) |
| `frontend/src/utils/snakeLayout.js` | 107 | Snake/wrapping workflow layout ("Snake" mode) |
| `frontend/src/config/layout.js` | 49 | Layout constants (single source of truth) |
| `frontend/src/hooks/useCytoscapeGraph.js` | 158 | Cytoscape lifecycle hook: init, drag, layout modes, role badges |
| `frontend/src/components/SqlPanel.jsx` | 326 | SQL display with syntax highlighting, edge range highlights, export |

### Edge Type System (16 types)
| Type | Color | Line | Width | Category |
|------|-------|------|-------|----------|
| TABLE_FLOW | #2ECC71 green | solid | 3 | structure |
| ALIAS | #1ABC9C teal | dashed | 1 | structure |
| REF | #27AE60 green | solid | 1 | copy |
| AGGREGATE | #8E44AD purple | solid | 3 | aggregate |
| TRANSFORM | #D35400 orange | dashed | 2 | compute |
| WINDOW | #9B59B6 purple | dashed | 2 | aggregate |
| COMPUTED | #E67E22 orange | dotted | 2 | compute |
| SCHEMA | #3498DB blue | dotted | 1 | structure |
| INDIRECT | #C0392B red | dot-dash | 1 | filter |
| FILTER | #E74C3C red | solid | 2 | filter |
| JOIN | #E91E63 pink | dashed | 2 | filter |
| CORRELATED | #FF5722 deep-orange | dotted | 2 | filter |
| DML | #2980B9 blue | double | 3 | write |
| SET_OP | #F1C40F yellow | dashed | 2 | combine |
| SUBQUERY | #16A085 teal | dotted | 2 | combine |
| SUBSET | #7F8C8D gray | dotted | 1 | structure |

### Layout Architecture
1. `config/layout.js` — all constants (single source of truth)
2. `layoutCore.js` — shared functions: computeFieldRelPos(), computeTableInfo(), applyLayout()
3. Individual layout algos (snakeLayout.js, elkLayout.js) — only compute table/script coordinates
4. `useCytoscapeGraph.js` — cytoscape lifecycle, drag handling, layout mode dispatch

### Key Design Decisions
- **Compound nodes**: Tables contain fields (no cytoscape compound — field positions managed manually via frozen offsets)
- **DML routing**: INSERT/UPDATE/DELETE edges route through query_output (qo_) intermediate nodes
- **Edge dedup (Bug 1)**: qo_ nodes suppress mechanism-1 source_table for DML targets
- **Bug 3 (v3.3.69)**: Compound edge types split into separate edges before `find_sql_range()` — no compound types in output
- **Bug 4 (v3.3.66)**: FILTER range extends to AND/OR continuation lines
- **Bug 5 (v3.3.67)**: Alias detection uses semantic analysis, not length heuristic

## Quick Reference Commands
```bash
# Restart backend
docker restart gps-sql-backend

# Health check
docker exec gps-sql-backend curl -s http://127.0.0.1:8000/api/health

# Run tests
docker exec gps-sql-backend python3 -m pytest tests/ -v

# Build + deploy frontend
cd /home/huangyf/work/sql_visualizer/frontend && npm run build && cd .. && rm -rf backend/app/static/* && cp -r frontend/dist/* backend/app/static/

# Update version + deploy
echo "3.3.XX" | docker exec -i gps-sql-backend tee /app/VERSION && echo "3.3.XX" > VERSION
docker restart gps-sql-backend
```
