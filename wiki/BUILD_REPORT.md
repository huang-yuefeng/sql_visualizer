# Build Report — V3.2.1

**Date:** 2026-07-17
**Version:** 3.2.1

## Build Status
- Frontend: ✅ PASS (vite build)
- Backend tests: ✅ 302/302 PASS
- Docker deployment: ✅ Containers running
- No console errors on page load

## Changes This Release

### Bug Fixes
1. **Syntax error in DataFlowApp.jsx** — `useEffect` for Esc key was placed inside `return` JSX block. Moved to component body.
2. **Syntax error in DataFlowGraph.jsx** — Flash edge `useEffect` was not properly closed; keyboard shortcuts `useEffect` was incorrectly nested inside it. Restructured both hooks.
3. **`line-style: double` invalid** — Cytoscape.js doesn't support `line-style: double`. Changed to `line-style: solid` with distinctive `line-dash-pattern: [8, 2, 3, 2]` for DML write edges.
4. **ELK.js import failure** — Dynamic import of `elkjs/lib/elk.bundled.js` failed in production build. Fixed with two-tier approach: try ESM import first, fall back to UMD script tag loading from `/elk.bundled.js`.
5. **Autocomplete dropdown blocking Search** — Dropdown overlapped Search button. Fixed by: removing setTimeout on blur, adding click-away handler via document mousedown listener.

### Features Added
6. **L1 edge hover tooltips** — Edge hover now shows type, description, and color for both L1 and L2 graphs.
7. **Edge directional arrows** — All edges now use `target-arrow-shape: triangle` with appropriate colors.

### Files Modified
- `frontend/src/DataFlowApp.jsx` — syntax fix
- `frontend/src/components/DataFlowGraph.jsx` — syntax fix + L1 edge tooltips
- `frontend/src/components/FilterPanel.jsx` — click-away handler
- `frontend/src/utils/graphStyles.js` — line-style double fix
- `frontend/src/utils/elkLayout.js` — two-tier ELK loading
- `frontend/vite.config.js` — external elkjs
- `backend/app/static/elk.bundled.js` — copied for static serving
- `VERSION` — 3.2.0 → 3.2.1

## Test Results
```
backend/tests/ — 302 passed, 0 failed
frontend build — successful (59 modules)
docker compose — containers running
```

## Known Remaining Gaps
1. Compound nodes (table with field children) — styles defined, not rendering yet
2. Operation nodes in L2 graph — styles defined, not wired to backend
3. Field direct/indirect grouping — not implemented
4. Edge type category legend expansion — 7 categories exist, legend needs update

## Deployment
```bash
cd ~/work/sql_visualizer
./build.sh   # Build frontend
./deploy.sh  # Deploy with docker
```

Service available at: http://localhost:8000
