# GPS SQL Data Flow Visualizer

> **Visualize data lineage inside SQL scripts.** Extract, classify, and explore every variable — from physical table columns through CTEs, window functions, and CASE expressions — as an interactive dependency graph.

Built for the **GPS (Global Payments System)** financial domain, this tool takes complex SQL scripts (CTEs, window functions, MERGE, UNION ALL, nested CASE, COALESCE/CAST chains) and produces a live graph where you can click any variable to see its definition, upstream sources, downstream consumers, and an AI-generated business explanation.

---

<p align="center">
  <em>🔍 Search variables · 🎨 Color/shape-coded by type · 🤖 Claude-powered NL explanations · 📋 Paste or upload SQL</em>
</p>

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Variable Types](#variable-types)
- [Test Suite](#test-suite)
- [Configuration](#configuration)
- [License](#license)

---

## Features

| Feature | Description |
|---|---|
| **Variable Extraction** | Parses SQL via `sqlglot` (MySQL dialect) and extracts every named reference — table columns, CTE aliases, computed expressions, window function outputs, CASE branches, and more |
| **Type Classification** | Each variable is tagged with one of **12 types** (`database_table`, `cte_column`, `window_result`, `aggregate`, `case_result`, …) |
| **Dependency Graph** | Builds directed edges between variables based on column references, tracking data flow through CTE chains, aggregations, and transformations |
| **Line Number Mapping** | Maps each variable back to its origin in the source SQL for easy auditing |
| **Interactive Visualization** | A Cytoscape.js graph with node shapes/colors keyed to variable type, hover highlighting, click-to-inspect, and search/filter |
| **Claude AI Explanations** | On-demand natural-language explanations of what each variable represents in the GPS payments domain, streamed via SSE |
| **REST API** | FastAPI backend with 6 endpoints — analyze SQL, list scripts, query variables, retrieve graph data, stream explanations |

## Architecture

```
SQL Text
    │
    ▼
┌────────────────────────┐
│  sqlglot Parser        │  MySQL dialect, error-tolerant
│  (extractor_v2.py)     │  Existing foundation: 760-line AST walker
└──────────┬─────────────┘
           │ raw AST
           ▼
┌────────────────────────┐
│  Variable Extractor    │  NEW — classifies every named expression
│  variable_extractor.py │  12 variable types, source-column tracking
└──────────┬─────────────┘
           │ 291 variables (avg per script)
           ▼
┌────────────────────────┐
│  Dependency Graph      │  NEW — connects variables via column refs
│  dependency_graph.py   │  101 edges across 5 GPS scripts
└──────────┬─────────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐ ┌──────────────┐
│FastAPI   │ │Claude API    │
│REST API  │ │(SSE stream)  │
└────┬─────┘ └──────┬───────┘
     │              │
     ▼              ▼
┌─────────────────────────┐
│  React + Cytoscape.js   │
│  Interactive Graph UI   │
└─────────────────────────┘
```

## How It Works — The 4-Stage Pipeline

Every SQL script flows through four stages, each building on the last.

### Stage 1: Parse & Classify (`variable_extractor.py`, 644 lines)

`sqlglot` parses the SQL into an AST. The extractor walks every node looking for **named things** and classifies each one into one of 12 variable types:

```
SELECT sb.total_amount AS batch_total_amount
       └──────────────┘    └──────────────────┘
       table_column        intermediate variable
```

**Classification rules** (derived from the sqlglot AST node type):

| SQL pattern | AST node | VariableType |
|---|---|---|
| `FROM gps_transactions` | `exp.Table` | `database_table` |
| `sb.amount` | `exp.Column` | `table_column` |
| `WITH batch_summary AS (...)` | `exp.CTE` | `cte_table` |
| Column alias inside a CTE | `exp.Alias` in CTE context | `cte_column` |
| `COUNT(*) AS cnt` | `exp.AggFunc` | `aggregate` |
| `ROW_NUMBER() OVER (...)` | `exp.Window` | `window_result` |
| `CASE WHEN ... END` | `exp.Case` | `case_result` |
| `COALESCE(x, 0)` | `exp.Coalesce` | `function_result` |
| `'SETTLEMENT'` | `exp.Literal` | `literal` |
| `(SELECT ...)` scalar subquery | `exp.Subquery` | `subquery_result` |
| `MERGE INTO target` | `exp.Merge` target | `merge_target` |
| One arm of `UNION ALL` | `exp.Union` branch | `union_branch` |

Each variable also captures **source columns** (which table columns feed into it), **source tables** (which physical tables it ultimately traces to), and its **full SQL expression** as a string. The variable ID is a deterministic MD5 hash of `script_name:context:name`, so the same SQL always produces the same IDs.

Key implementation detail: `expr.this` is used (not `expr.unnest()`) to unwrap `Alias` nodes and reach the inner expression for type checking. The CTE context is tracked on a stack so columns defined inside `WITH ... AS` are correctly reclassified from `intermediate` → `cte_column`.

### Stage 2: Build Dependencies (`dependency_graph.py`, 110 lines)

For each variable's `source_columns`, we look for upstream variables whose **name** matches. When found, a directed edge is created:

```
sb.total_amount ──────────► batch_total_amount
(table_column)     REF      (intermediate)
```

**Edge relationship types** are derived from the *target* variable's type:

| Target type | Relationship | Meaning |
|---|---|---|
| `aggregate` | `AGGREGATION` | Source feeds into SUM/COUNT/AVG |
| `window_result` | `WINDOW` | Source is a PARTITION BY / ORDER BY column |
| `case_result` | `CASE_BRANCH` | Source appears in WHEN/THEN/ELSE |
| `function_result` | `TRANSFORMATION` | Source is wrapped in COALESCE/CAST/etc. |
| anything else | `DIRECT_REFERENCE` | Plain column reference |

Two indexes speed up matching: a `name → [variables]` lookup and a `full_column_ref → variable` lookup. Self-loops are prevented, and each source-target pair creates at most one edge.

### Stage 3: Natural Language Explanation (`claude_service.py`, 117 lines)

Variable metadata is packaged into a prompt and sent to **Claude Opus 4.8** with adaptive thinking:

- **System prompt**: Positions Claude as a GPS financial SQL analyst
- **User prompt**: Script name + JSON array of variables (name, type, SQL expression, source tables, context)

Claude responds with structured explanations covering five dimensions:

```json
{
  "business_meaning": "Total monetary value of transactions settled in this batch",
  "computation": "Sum of gps_transactions.amount grouped by settlement_batch_id",
  "data_lineage": "Traces to gps_transactions.amount → batch_summary CTE → final output",
  "dependencies": "Depends on gps_transactions.amount and GROUP BY on settlement_batch_id",
  "business_significance": "Critical for reconciliation — variance against batch_total triggers investigation"
}
```

The response is **streamed via SSE** (`text/event-stream`) so the frontend can render text token-by-token. If `ANTHROPIC_API_KEY` is not set, the endpoint returns a graceful fallback message instead of crashing.

### Stage 4: Visualize (React + Cytoscape.js)

The backend's `graph_service.py` converts variables and dependencies into **Cytoscape.js-compatible JSON** — each variable becomes a node with pre-computed `shape`, `color`, and `size` based on its type. Each dependency becomes an edge with `source` and `target` IDs.

The frontend renders this as an interactive force-directed graph:

| Interaction | Behavior |
|---|---|
| **Click node** | Opens detail panel: SQL expression, source columns, upstream/downstream dependencies |
| **Hover node** | Highlights the node and its immediate neighbors, dims everything else |
| **Search bar** | Dims nodes whose name doesn't match; matching nodes glow |
| **Type dropdown** | Shows only nodes of the selected VariableType |
| **"Explain with AI"** | Streams Claude's explanation into the detail panel in real-time |
| **Fit button** | Re-centers and zooms the graph to show all nodes |

## Data Model

Two types form the backbone of the entire system:

```
VariableDefinition
├── id: "a1b2c3d4e5f6g7h8"     # content-hash, stable across runs
├── name: "batch_total_amount"  # the alias or column name
├── variable_type: INTERMEDIATE # one of 12 enum values
├── sql_expression: "sb.total_amount AS batch_total_amount"
├── source_columns: ["sb.total_amount"]
├── source_tables: ["gps_settlement_batches"]
├── defined_in: "SELECT"        # or "CTE:batch_summary", "MERGE"
├── line_start: 12              # line in source SQL
├── line_end: 12
└── is_output: true             # final SELECT column?

VariableDependency
├── source_id: "a1b2..."        # produces data
├── target_id: "x9y0..."        # consumes data
├── relationship: "TRANSFORMATION"
├── operation: "REFERENCE"
└── sql_context: "sb.total_amount -> batch_total_amount"
```

Everything else — graph nodes, API responses, the frontend state — is a projection of these two types.

## Project Structure

```
sql_understanding/
├── README.md
│
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                      # FastAPI entry point
│   │   ├── config.py                    # Environment config
│   │   ├── models/
│   │   │   ├── variable.py              # VariableType enum, VariableDefinition, VariableDependency
│   │   │   ├── graph.py                 # DataFlowGraph, GraphNode, GraphEdge
│   │   │   └── api_models.py            # Request/response Pydantic schemas
│   │   ├── extractor/
│   │   │   ├── variable_extractor.py    # Core: AST → VariableDefinition list
│   │   │   ├── dependency_graph.py      # VariableDefinition list → dependency edges
│   │   │   ├── sql_line_mapper.py       # Variable ↔ SQL line number mapping
│   │   │   ├── adapter.py               # Orchestrates all extraction phases
│   │   │   └── extractor_v2.py          # Existing sqlglot-based SQL parser
│   │   ├── services/
│   │   │   ├── analysis_service.py      # Full pipeline + file-based caching
│   │   │   ├── graph_service.py         # Cytoscape.js-compatible nodes/edges
│   │   │   └── claude_service.py        # Anthropic SDK streaming explanations
│   ├── static/                      # Pre-built frontend (served in production)
│   ├── vendor/                      # 31 Python wheels for offline install
│   │   └── routers/
│   │       ├── analysis.py              # POST /analyze, GET /scripts
│   │       ├── graph.py                 # GET /scripts/{id}/graph
│   │       └── variables.py             # GET /variables, POST /explain
│   ├── tests/
│   │   ├── conftest.py                  # Shared fixtures
│   │   ├── test_variable_extractor.py   # 17 tests — variable extraction + classification
│   │   ├── test_dependency_graph.py     # 6 tests — dependency edges + integration
│   │   └── test_data/                   # 6 minimal SQL fixtures
│   └── analysis_cache/                  # File-based result cache
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx                     # React entry point
│       ├── App.jsx                      # Main app: graph, sidebar, detail panel
│       ├── api/client.js                # Fetch wrapper for all backend endpoints
│       ├── utils/graphStyles.js         # Cytoscape.js stylesheet + layout config
│       └── styles/app.css               # Dark-theme UI styles
│
└── samples/
    └── financial/                       # 5 real GPS financial SQL scripts + DDL
        ├── tables_financial.sql          #   8 GPS tables (transactions, accounts, …)
        ├── fin_query1_reconciliation.sql #   CTEs + window functions (ROW_NUMBER, LAG, SUM)
        ├── fin_query2_fee_calculation.sql#   Multi-join + CASE + JSON_EXTRACT + subqueries
        ├── fin_query3_account_balance.sql#   LAG/LEAD + AVG OVER + RANK + NTILE
        ├── fin_query4_merge_upsert.sql   #   MERGE INTO + INSERT INTO SELECT
        └── fin_query5_union_risk_report.sql#  4 CTEs + UNION ALL + PERCENT_RANK
    └── backend/
        └── vendor/                          # 31 Python wheels for offline install (7.3 MB)
        └── app/
            └── static/                      # Pre-built frontend (served by FastAPI in production)
```

## Quick Start

### Online (with internet)

**Prerequisites:** Python 3.10+, Node.js 18+

```bash
# Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# → API at http://localhost:8000, Swagger at /docs

# Frontend (dev mode — separate terminal)
cd frontend
npm install
npm run dev
# → UI at http://localhost:5173 (proxies /api to :8000)
```

### Offline (air-gapped / no internet)

All Python dependencies are **pre-downloaded** into `backend/vendor/` (31 wheels, 7.3 MB). The frontend is **pre-built** into `backend/app/static/` and served directly by FastAPI — **no Node.js, no npm, no network needed at runtime**.

**Prerequisites:** Python 3.10+ (with `pip`)

```bash
cd backend

# 1. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install all dependencies from bundled vendor folder (no network)
pip install --no-index --find-links=vendor/ -r requirements.txt

# 3. Start the server — API + frontend served from a single process
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` — the API, Swagger docs (`/docs`), and the interactive graph UI are all served from one command.

> **Note on platform wheels:** The `vendor/` folder contains Linux x86_64 wheels (`manylinux_2_17_x86_64`). To re-bundle for a different platform (arm64, macOS, Windows), run this on a machine *with* internet, then transfer the `vendor/` folder:
> ```bash
> pip download -r requirements.txt -d vendor/
> ```

### (Optional) Enable AI Explanations

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

When the key is set, clicking **"Explain with AI"** on any variable streams a natural-language explanation from Claude Opus 4.8. Without the key, the endpoint returns a graceful fallback message.

## API Reference

### Analyze SQL

```http
POST /api/analyze
Content-Type: multipart/form-data
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sql_text` | string | Yes | SQL script content |
| `script_name` | string | No | Label for the script (default: `unnamed.sql`) |

**Response:**
```json
{
  "script_id": "9ff2dd02c590",
  "script_name": "fin_query1_reconciliation.sql",
  "total_variables": 57,
  "total_dependencies": 18,
  "table_count": 2,
  "cte_count": 3
}
```

### List Scripts

```http
GET /api/scripts
```

Returns summaries of all previously analyzed scripts.

### Get Full Analysis

```http
GET /api/scripts/{script_id}
```

Returns the complete analysis: variables, dependencies, line map, and metadata.

### Get Graph Data

```http
GET /api/scripts/{script_id}/graph
```

Returns Cytoscape.js-compatible `nodes` and `edges` arrays with styling metadata (shape, color, size) pre-populated per variable type.

### List Variables

```http
GET /api/scripts/{script_id}/variables?search=amount&type=aggregate
```

Filters variables by name substring and/or type. Returns each variable with its SQL expression, source columns, source tables, and line numbers.

### Get Variable Detail

```http
GET /api/scripts/{script_id}/variables/{var_id}
```

Returns the variable plus its upstream dependencies (what it depends on) and downstream dependencies (what depends on it).

### Explain with AI

```http
POST /api/scripts/{script_id}/explain
Content-Type: application/json

{ "variable_ids": ["abc123", "def456"] }
```

Streams an SSE response with Claude's explanation. Send an empty `variable_ids` array to explain all variables. Requires `ANTHROPIC_API_KEY`.

## Variable Types

Every variable extracted from SQL is classified into one of these types:

| Type | Shape (in graph) | Example |
|------|-------------------|---------|
| `database_table` | Blue rectangle | `gps_transactions` |
| `table_column` | Light blue circle | `gps_transactions.amount` |
| `cte_table` | Green rounded rect | `batch_summary` |
| `cte_column` | Green triangle | Column defined inside a CTE |
| `intermediate` | Orange diamond | Aliased computed expression |
| `window_result` | Purple hexagon | `ROW_NUMBER() OVER (...)` |
| `aggregate` | Teal triangle | `SUM(t.amount)`, `COUNT(*)` |
| `case_result` | Pink pentagon | `CASE WHEN ... THEN ... END` |
| `function_result` | Yellow rhomboid | `COALESCE(t.tax, 0)` |
| `literal` | Gray circle | `'SETTLEMENT'` constant |
| `merge_target` | Red rectangle (bold) | Target table in `MERGE INTO` |
| `union_branch` | Silver vee | One arm of `UNION ALL` |

Each variable object also carries:

| Field | Description |
|-------|-------------|
| `id` | Unique 16-char hash |
| `name` | Variable name (alias or column) |
| `sql_expression` | Full SQL text defining this variable |
| `source_columns` | Physical columns this derives from |
| `source_tables` | Physical tables this traces to |
| `defined_in` | Context (`CTE:batch_summary`, `SELECT`, `MERGE`) |
| `line_start` / `line_end` | Line numbers in the source SQL |
| `is_output` | Whether this is a final SELECT output |

## Test Suite

Tests are written **before** each production module (TDD):

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -v
```

```
tests/test_variable_extractor.py  — 17 tests
  ├── TestSimpleVariableExtraction   (5 tests) — basic SELECT, aliases, table detection
  ├── TestCTEVariableExtraction      (2 tests) — CTE tables and columns
  ├── TestWindowFunctionExtraction   (1 test)  — ROW_NUMBER, LAG, LEAD, SUM OVER, RANK
  ├── TestCaseExtraction             (1 test)  — CASE WHEN + nested CASE
  ├── TestFunctionResultExtraction   (1 test)  — COALESCE, CAST, JSON_EXTRACT
  ├── TestMergeExtraction            (1 test)  — MERGE INTO
  ├── TestUnionExtraction            (1 test)  — UNION ALL with CTEs
  └── TestIntegration                (5 tests) — all 5 GPS financial samples

tests/test_dependency_graph.py — 6 tests
  ├── TestSimpleDependencies  (2 tests) — basic edges, no self-loops
  ├── TestCTEDependencies     (2 tests) — CTE chain edges, valid IDs
  └── TestDependencyIntegration (2 tests) — fin_query1 + fin_query4 E2E

23 tests passed ✅
```

## Configuration

All settings are read from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key for Claude explanations |
| `ANTHROPIC_MODEL` | `claude-opus-4-8` | Model ID for explanations |
| `HOST` | `0.0.0.0` | FastAPI listen host |
| `PORT` | `8000` | FastAPI listen port |
| `DEBUG` | `true` | Enable debug mode |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |

## GPS Domain Context

The sample SQL scripts model a **Global Payments System** with 8 core tables:

| Table | Purpose |
|-------|---------|
| `gps_transactions` | Payments, refunds, chargebacks, reversals |
| `gps_accounts` | Customer/merchant balances, limits, KYC status |
| `gps_settlement_batches` | Batch processing, clearinghouse settlement |
| `gps_reconciliation` | Internal/external/GL/bank reconciliation |
| `gps_exchange_rates` | FX spot/forward rates with bid/ask/mid |
| `gps_fee_schedules` | Tiered fee structures (percentage/flat/hybrid) |
| `gps_risk_scores` | ML/rule/velocity/device/geo risk scores |
| `gps_audit_trail` | Entity-level change tracking, approval workflow |

All sample DDL and queries are in [`samples/financial/`](samples/financial/).

## Roadmap

- [ ] Cross-script data lineage (variable tracking across multiple SQL scripts)
- [ ] Column-level lineage through CTE chains (exact column-to-column mapping)
- [ ] Export graph as PNG/SVG
- [ ] Database connection — auto-discover table schemas
- [ ] Diff mode — compare two versions of a SQL script

## License

MIT
