# GPS SQL Data Flow Visualizer — AI Context Guide

## Project Overview
Online web service that extracts variables from GPS financial SQL scripts, builds dependency graphs, and renders interactive Cytoscape.js visualizations.

- **Backend**: FastAPI + sqlglot (MySQL dialect)
- **Frontend**: React + Vite + Cytoscape.js
- **Version**: See `/VERSION` file
- **Tests**: 187 tests in `backend/tests/`

## Module Map (read only what you need)

### Core Domain Model (ALWAYS read first for type questions)
| File | Size | What it contains |
|------|------|-----------------|
| `backend/app/models/variable.py` | ~110L | VariableType enum (15 types), VariableDefinition, VariableDependency |
| `backend/app/models/sql_model.py` | ~170L | Canonical taxonomy: node↔edge types mapped to SQL data objects |

### Extraction & Graph Building (read for extraction/bugs/features)
| File | Size | What it contains |
|------|------|-----------------|
| `backend/app/extractor/variable_extractor_v2.py` | ~635L | Role-based Identifier walking — the core extractor |
| `backend/app/extractor/dependency_graph.py` | ~445L | 12-phase edge creation algorithm |

### Services (read for API/output questions)
| File | Size | What it contains |
|------|------|-----------------|
| `backend/app/services/graph_service.py` | ~145L | Cytoscape JSON builder, node styles, edge colors |
| `backend/app/services/topology_checker.py` | ~200L | 6 registered integrity checks |
| `backend/app/services/io_graph_service.py` | ~240L | BFS path finding from input→output columns |
| `backend/app/services/multi_script_service.py` | ~100L | Cross-script shared variable detection |
| `backend/app/services/analysis_service.py` | ~66L | Pipeline orchestration with file-based JSON cache |

### API Layer (read for endpoint questions)
| File | Size | What it contains |
|------|------|-----------------|
| `backend/app/routers/analysis.py` | ~80L | POST /analyze, GET /scripts, POST /analyze_multi |
| `backend/app/routers/graph.py` | ~40L | GET /graph, POST /io_graph |
| `backend/app/main.py` | ~50L | FastAPI app initialization |

### Frontend (read for UI questions)
| File | Size | What it contains |
|------|------|-----------------|
| `frontend/src/App.jsx` | ~370L | Main React component (graph, filters, legend, panels) |
| `frontend/src/utils/graphStyles.js` | ~92L | Cytoscape stylesheet + layout config |

### Tests (read for test patterns)
| File | Tests | What it covers |
|------|-------|---------------|
| `backend/tests/test_node_types.py` | 53 | Per-node-type coverage — every type reachable from SQL |
| `backend/tests/test_edge_types.py` | 27 | Per-edge-type existence + regression tests |
| `backend/tests/test_graph_integrity.py` | 22 | Topology checks against all SQL samples |
| `backend/tests/test_variable_extractor.py` | 16 | Core extraction correctness |
| `backend/tests/test_complex_samples.py` | 30 | DWH analytics samples (13 scripts) |
| `backend/tests/test_analytical_samples.py` | 10 | TPC-DS style analytical queries |
| `backend/tests/test_github_inspired_samples.py` | 29 | Real-world GPS patterns |

## Key Design Decisions

### Node Type System (v2.2.0 — current)
15 variable types grouped into 6 categories:
- **Data Sources**: `table`, `view`, `cte`, `subquery`, `virtual_table`
- **Column Refs**: `column`, `cte_column`
- **DML Targets**: `merge_target`
- **Set Operations**: `union_branch`
- **Computed**: `aggregate`, `window`, `case`, `transform`, `expression`
- **Literals**: `literal`

### Edge Type System (v2.0.0)
14 edge types: SCHEMA, ALIAS, SELECT, JOIN, SET_OP, REF, AGGREGATE, TRANSFORM, WINDOW, COMPUTED, INDIRECT, FILTER, DML, SUBSET

### Deduplication
Variables are globally deduplicated by `(name, type.value)`. CTE_TABLE overrides DATABASE_TABLE when both exist.

### Alias vs Original Name
Only aliases get SCHEMA (BELONGS_TO) edges. Original table names are registered but don't get column ownership edges — that would be redundant.

### Connectivity Rules
- **table_column** (`column`): must have ≥2 edges
- **table** (`table`): only needs ≥1 edge (columns cover the data flow)
- All other types: must have ≥1 edge

## How to Work on This Project Efficiently

1. **For type system questions**: Read only `models/variable.py` and `models/sql_model.py` (~280 lines total)
2. **For extraction bugs**: Read `extractor/variable_extractor_v2.py` + the relevant test file
3. **For edge/graph questions**: Read `extractor/dependency_graph.py`
4. **For frontend changes**: Read `frontend/src/App.jsx` + `services/graph_service.py`
5. **Always run tests after changes**: `cd backend && ./venv/bin/python -m pytest tests/ -x`

## Context Management Tips

- Reference this file at session start: "Read CLAUDE.md to understand the project"
- Ask Claude to read specific modules rather than the whole project
- The `sql_model.py` file encodes all domain knowledge in one place — read it for any type-related question
- Test data files in `samples/` are large — exclude them from context unless debugging a specific query
- Use `.claude/ignore` to exclude `backend/venv/`, `node_modules/`, and `analysis_cache/`
