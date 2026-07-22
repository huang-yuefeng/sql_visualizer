# SQL Visualizer — Development Guide v3.2.15

## Quick Start

```bash
cd ~/work/sql_visualizer

# 1. Start hot-reload frontend (run once, keep running)
docker compose up frontend -d
# → Frontend at http://localhost:5173 (edit JSX → instant update)

# 2. Edit source code in frontend/src/
#    Changes reflect instantly at :5173

# 3. When ready to ship to production (backend serves static):
./fast_deploy.sh
# → Builds + copies to backend/static in ~1.3s

# 4. Run automated tests (optional, verify nothing broke):
cd tests/playwright && npx playwright test --reporter=list
# → 6 tests in ~15s
```

---

## Daily Workflow

### Option A: Hot-reload dev (recommended)

| Step | Command | Time |
|------|---------|------|
| Start frontend | `docker compose up frontend -d` | once |
| Edit code | open `frontend/src/` in editor | — |
| See changes | browser at `http://localhost:5173` | instant |
| Deploy to prod | `./fast_deploy.sh` | 1.3s |
| Verify | `cd tests/playwright && npx playwright test` | 15s |

### Option B: Build-deploy-test loop (no Docker)

| Step | Command | Time |
|------|---------|------|
| Edit code | open `frontend/src/` in editor | — |
| Build + deploy | `./fast_deploy.sh` | 1.3s |
| Test manually | browser at `http://localhost:8000` | — |
| Run tests | `cd tests/playwright && npx playwright test` | 15s |

---

## File Map

```
sql_visualizer/
├── fast_deploy.sh          ← One-click build + deploy
├── VERSION                 ← Bump this to invalidate caches
├── frontend/src/
│   ├── api/client.js       ← API calls (+ cache busting)
│   ├── hooks/useCytoscapeGraph.js  ← Cytoscape graph logic
│   ├── utils/graphStyles.js        ← Node/edge CSS styles
│   ├── components/
│   │   ├── DataFlowGraph.jsx       ← L1/L2 graph component
│   │   ├── SqlPanel.jsx            ← SQL display + export
│   │   ├── FilterPanel.jsx         ← Search panel
│   │   └── WorkspacePanel.jsx      ← Upload + file tree
│   └── DataFlowApp.jsx             ← Main app layout + state
├── backend/app/services/
│   └── dataflow_service.py         ← Graph building + analysis
└── tests/playwright/
    └── dataflow.spec.js            ← 6 automated tests
```

---

## Cache Invalidation

When you change the backend analysis logic, bump VERSION:

```bash
echo "3.2.16" > VERSION
```

This automatically:
1. Invalidates all graph caches (`graph_3_2_16_*.json` vs old `graph_3_2_15_*.json`)
2. Appends `?v=3.2.16` to all API requests (no browser cache)
3. Updates the `<meta name="version">` tag

No manual cache clearing needed.

---

## Test Suite

```
tests/playwright/dataflow.spec.js — 6 tests:

R1: Upload folder and see file tree
R2: Search table.field shows L1 graph (5 script nodes)
R3: Double-click script opens L2 with edges
R4: Edge click highlights SQL line
R5: No field nodes exceed table bounds
R6: Zero console errors after full workflow
```

Run:
```bash
cd tests/playwright
npx playwright test --reporter=list   # all 6
npx playwright test -g "R4"           # just R4
npx playwright test --headed          # watch browser
```

---

## Common Tasks

```bash
# Check version
curl http://localhost:8000/api/health
# → {"status":"ok","version":"3.2.15"}

# Check if frontend dev server is running
curl -s http://localhost:5173 | head -1
# → <!DOCTYPE html>

# Stop frontend dev server
docker compose stop frontend

# View Docker logs
docker compose logs backend --tail=20

# Rebuild Docker image after backend changes
docker compose build backend && docker compose up -d backend

# Clear all Docker data (volumes + containers)
docker compose down -v && docker compose up -d
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Data-driven table heights (`data(_tableHeight)`) | Avoids `renderedBoundingBox` bug in Cytoscape |
| Event handler ref indirection | Always calls latest callback, not stale closure |
| Field gap = 40px (FIELD_H) | Prevents label overlap, readable at any zoom |
| Versioned cache keys | Code change = auto cache invalidation |
| Synthetic `…` fields for empty tables | Prevents "empty table" visual but needs backend fix |

---

## Known Limitations

| Issue | Workaround |
|-------|-----------|
| Empty tables in L2 (aliased real tables) | Fields assigned to aliases (`so`→`stg_orders`). Shows with 80px min-height |
| `fast_deploy.sh` overwrites prod static | Back up with `cp -r backend/app/static backend/app/static.bak` |
| Cytoscape `renderedBoundingBox` unreliable | Use `_tableHeight` data attribute instead |
