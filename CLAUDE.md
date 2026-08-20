# CLAUDE.md — SQL Data Flow Visualizer

> Auto-generated snapshot for AI-assisted development. Update after major refactors.

## Project Overview

A **SQL data flow debugger** with 3-panel React frontend and FastAPI Python backend.
Parses SQL scripts → extracts variables + dependencies → renders interactive
Cytoscape.js data flow graphs (L1 cross-script pipeline, L2 per-script detail).

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker `gps-sql-backend` on port 8000
- **Frontend**: React 18 + Vite + Cytoscape.js, served from `frontend/dist/`
- **Tests**: vitest (frontend, 167 passed across 15 files), pytest (backend, 870 passed / 5 skipped in `backend/tests/`)
- **Version**: See `/VERSION` (currently 3.3.160)
- **Service IP**: `192.168.0.66:8000` (never use `localhost`)

## File Map (Key Source Files)

### Backend (`backend/app/`)

| File | Lines | Role |
|------|-------|------|
| `routers/dataflow.py` | 535 | `GET /api/workspace/{ws_id}/views/{view_id}/level1`, `GET .../level2?script=&filter=`, `POST .../search`, view CRUD, `GET .../scripts/{name}/highlight` (R22: level1 lineage filter, base-index diagnostics) |
| `routers/workspace.py` | 240 | `/api/workspace` CRUD (DELETE: 400 malformed / 404 missing / 200 deleted), scan, index, filter-config, export-config, autocomplete |
| `routers/analysis.py` | 73 | Legacy `/api/analyze`, `/api/scripts`, `/api/analyze_multi` |
| `services/filter_service.py` | 531 | **Filter logic** (R19): CSV parse → scopes → A∩B intersection → filter application + diagnostics (F6); shared `resolve_script` (R5, path-containment-checked); F3/F4/F5 (COL_NAME-only rows dropped + `ignored_rows` counters, case folding) |
| `services/l1_builder.py` | 1136 | Cross-script L1 builder (production BFS → lineage_field_pairs → filter); M4-B degraded fallback (`degraded: true` + diagnostic); C2 single-cache-pass (R24: single-script workspaces run the full pipeline inline — script node + tables + edges, clickable to L2). **C-H1 (v3.3.160)**: `_lookup_analysis` — exact sql-keyed cache read requiring both extractor_version AND sql_text to match (edited-script stale analysis rejected) |
| `services/l2_builder.py` | 1794 | Per-script L2 builder; C1 split into named phases (`_build_edge_list`, `_simplify_dml_edges`, `_map_search_target_ids`, ...) — byte-identity-verified. **R22: one compound node per physical table** (label-keyed merge, `merged_original_ids`, `search_matched` in return dict). **v3.3.138 (B-series)**: dedup key `(parent_table_id, undecorated_label, stmt_idx)` — B4 no `↻` twins, C-9 per-statement fields; `_resolve_scope_parent` context-segment walk (B3); label/table_name split for `⟐` (B5); `_load_or_build_graph` prefers S4b-mutated analysis caches (C-2b/C-10). **v3.3.139**: D2 `(0,0)` highlight filter + `_recompute_line_map` stale-cache defense; `_scope_distance`/`_pick_scope_candidate` scope-aware parenting + seed re-parent onto searched table (B3/P1); Sync 1 iterates all same-name aliases (p1 sync live); P2 target seed fields keep field-level edges. **v3.3.140 (strict table.field flow)**: `_apply_relevance_filter` switches to `filter_by_field_flow` (legacy `filter_relevant` kept for L1); highlights = single `[line,line]` from node-carried `line_start` of field-like closure vars (FIELD_LIKE_TYPES/PARTITION, D2 guard); P1 MOVE→COPY — seed copies (`seed_{id}_{keeper[:8]}`) land on alias/CTE/target nodes, all `is_target`; ctx-aware parent refinement (`_pick_scope_candidate`); Sync 1/2 stmt_idx-aware (C7); alias dedup key `(alias_parent_id, label, alias_line)` with `p1@29` display labels; JOIN edges survive only when touching the seed zone (seed-side JOIN only). **v3.3.145**: scope-context patch machinery deleted (`_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent`); `_compute_highlight_ranges` delegates to `get_strategy("single_line")`; `_load_or_build_graph` stamps `parse_errors` into graph caches |
| `services/dataflow_service.py` | 780 | SearchView, view persistence (views.json, persists match_mode), edge style helpers (R22: no-matches search semantics, L2 `search_matched`/not-in-flow full-graph response; R24: single-script L1 never pruned by the disconnected-script rule; C-2b: miss path builds from analysis cache + writes graph cache format_version 3). **v3.3.140**: relevance filter via `filter_by_field_flow` (legacy `filter_relevant` re-export kept for sql_highlight_service), format_version 4 + `extractor_version` mismatch re-run. **v3.3.145**: `get_level2_graph(..., highlight_strategy="single_line")` + `?highlight_strategy=` query param (label_only → no highlights; unknown names fall back to single_line); `parse_errors` in level2 response (case-3 diagnostics). **v3.3.160**: L2 two-view field-flow closure — `flow_node_ids`/`flow_edge_ids` in the response plus byte-identical `full_graph` for the client-side flow-only ↔ full toggle; C-H1 exact sql-keyed analysis cache (md5 of `EXTRACTOR_VERSION|script|sql`) |
| `services/folder_index_service.py` | 1508 | Folder scanning, script indexing, **A1 schema-file classification** (`file_class: schema\|script`), **S4b cross-script schema auto-resolution** (R22: two-phase plan→conflict-detect→apply, ambiguous fields revoked + `resolution_stats["ambiguous"]`, context-scoped cache attribution), resolution_stats aggregation, orphan report, index progress, `schema_evidence` in response. **v3.3.138 (C-series)**: CTAS→script (C-1), `_invalidate_graph_caches` post-S4b + index-time graph precompute REMOVED (C-2a), `_revoke_s4b_cache_update` (C-3), post-loop star expansion (C-5), `parse_by_script`/`parsed_cache` single parse (C-13a). **v3.3.139**: C-4 apply-side `n_attributed>0` gate; C-5 star expansion excludes revoked/ambiguous fields. **#245**: SELECT-output aliases (Fix A) + INSERT column names indexable for autocomplete (Bug 49 alias→physical, Bug 41 DML cross-ref); typo-tolerant matcher — substring primary, Levenshtein-≤1 fallback ranked exact > prefix > dist-1 |
| `services/cache_keys.py` | 107 | `GRAPH_CACHE_PREFIX = "graph_3_2_19"` (single source of truth; bumped v3.3.145 for def-line/alias/containment graphs) |
| `services/graph_service.py` | 326 | Cytoscape JSON builder, NODE_STYLES, EDGE_TYPE_STYLE/CATEGORY_MAP, table_fields/alias_map; `_stmt_idx_of` + context/stmt_idx in node data (C-9); `line_start`/`line_end` in node data (v3.3.140); copies `containment` onto graph edge data (v3.3.145, I5 — the flag must reach the walker/filter) |
| `services/highlight_strategies.py` | 268 | Display module (v3.3.145): `STRATEGIES` dict + `get_strategy(name)` — default `single_line` (node-carried `line_start`, D2 line-0 filter, adjacent-line merge), `label_only` → `[]`; unknown names fall back; extensible for future strategies (span etc.) |
| `services/logger.py` | 183 | SSE pipeline logger (ref-counted queue cleanup) |
| `extractor/variable_extractor_v2.py` | 3142 | Role-based Identifier walking + S1–S6 orphan resolution; **S4a auto-attribution** (`_finalize_schema_candidates`, R6 field==table collision guard), statement-anchored loc (R22-L16: type-aware `_is_as_keyword` — string literals never the anchor; C-13b: token-position anchor), dict-of-dicts script_schemas; C4a unified stats (`resolved`/`unresolved_count`/`coverage_pct`). **v3.3.138**: contexts `TOP{stmt_idx}` (C-9), `_walk_join_key_expressions` (B-series Phase 2), label sanitation (B5). **v3.3.139**: order-independent join-key pairing (`_pair_join_key_sides`). **v3.3.140**: phantom dedup (`_explicitly_walked_selects` prune — subquery-interior columns registered once); statement-scoped line lookup (`_stmt_anchor_lines` + `_record_stmt_anchor` at `_walk_select/_walk_insert/_walk_merge/_walk_create`, `_find_position_scoped` — text-search expr[:40] within `[anchor, next_anchor)`, nested-context anchors excluded; `_add` uses it); PARTITION walk handles `exp.Column` + `exp.EQ`(Column left) on the Table node; `EXTRACTOR_VERSION = "2026-08-07.2"`. **v3.3.145 (I1/I2, definition-line resolution)**: vars carry DEF-site lines from the pre-tokenized stream (`self._tokens`, token `.line/.col`, 1-based) — `_find_position_scoped` text-search DELETED (patch layer); `_stmt_anchor_for(context)`; I2: `_register_column` sets `var.source_tables = [_resolve_alias(table, scope)]` (no early return — qualified columns attributed at extraction time); B3: `_attribute_output_containers` post-pass (CTE body outputs → own CTE, subquery/derived outputs → own VIRTUAL_TABLE); records `parse_errors` on ExtractionResult (case-3); `EXTRACTOR_VERSION = "2026-08-08.1"` |
| `extractor/dependency_graph.py` | 981 | VariableDefinition → VariableDependency (16 edge types); Phase 6b JOIN-key expression edges + REF classification (B-series Phase 2). **v3.3.145 (I3/I4)**: Phase 2 ALIAS = one edge per `alias_of` exact source-var id (name-matching cross-product DELETED; `id_index`/`var_order` support); Phase 7/8 anchors via `_pick_anchor` (candidates `_TABLE_TYPES` with `0 < line_start <= v.line_start`, max line, ties: empty `source_tables` > non-VIRTUAL_TABLE > registration order; `_parent_ctx` ancestor walk; global first-match DELETED; no candidate → skip); Phase 4b tags SCHEMA container→nested ⟐VT edges `containment=True` (I5) |
| `extractor/sql_line_mapper.py` | 86 | SQL expression → line mapping for `highlights` (D1: comment lines skipped, v3.3.139). **v3.3.140**: prefers var-carried `line_start`/`line_end` (statement-scoped) when > 0; text search kept as stale-cache fallback |
| `extractor/lineage.py` | 1537 | `compute_field_lineage()`, `filter_relevant()` (R18). **v3.3.138 (B-series Phase 1)**: SUBSET `{propagates_value: False, always_bidir: False}` — never walkable; JOIN rule admits expression nodes unconditionally, others on production evidence; None-guards. **v3.3.140**: `compute_field_flow()`/`filter_by_field_flow()` — strict table.field walker (FIELD_LIKE/FIELD_LAND/NEVER sets; ALIAS iff source_tables[0]==target; FILTER/JOIN iff seed-zone endpoint; DML forward-only; owner resolution + container rule; identity admissions to fixpoint) — legacy functions byte-identical. **v3.3.145 (I5)**: containment edges excluded — `_is_containment(ed)` helper (dict-key + object-attr forms), skipped in `compute_field_flow` adjacency + `filter_by_field_flow` output |
| `extractor/schema_inference.py` | 180 | `infer_table_schemas()` — 7-pass iterative stabilization |
| `models/variable.py` | 127 | VariableType enum (15 types), VariableDefinition, VariableDependency; `VariableDefinition.alias_of` (I4: exact source var id for ALIAS edge) + `VariableDependency.containment` (I5) |
| `models/sql_model.py` | 161 | Canonical taxonomy: node↔edge types mapped to SQL |

### Frontend (`frontend/src/`)

| File | Lines | Role |
|------|-------|------|
| `DataFlowApp.jsx` | 696 | Data Flow Debugger main component (search, view persistence, resolution report, `schema_evidence` state; R22: `applyL2Result` + L2 not-in-flow banner, L1 no-matches message banner; R23: no browser auto-restore — clean start on load, one-time `df_last_search_view` purge) |
| `App.jsx` | 857 | SQL Analysis (legacy single-script) |
| `components/DataFlowGraph.jsx` | 306 | Cytoscape renderer (no edge-hover tooltip — removed #240) |
| `components/SqlPanel.jsx` | 329 | SQL display + syntax highlighting |
| `components/FilterPanel.jsx` | 345 | Filter upload UI + warning banner (R2), renders `ignored_rows` |
| `components/ResolutionReport.jsx` | 99 | Orphan resolution coverage badge + breakdown (R20) |
| `components/WorkspacePanel.jsx` | 75 | Workspace upload/scan/index UI |
| `utils/layoutCore.js` | 244 | Shared layout: `fieldPositionsForTable()`, `positionTableFields()`, `applyLayout()` |
| `utils/snakeLayout.js` | 107 | Snake/wrapping layout |
| `utils/elkLayout.js` | 239 | ELK layered layout |
| `utils/resolutionReport.js` | 93 | Stats normalization (prefers unified `unresolved_count`/`coverage_pct`) |
| `utils/flowVisibility.js` | 60 | L2 two-view toggle helper: resolves initial flow-only state and applies `.show()/.hide()` visibility from `flow_node_ids`/`flow_edge_ids` (never re-layout — positions preserved across toggles) |
| `utils/nameFilter.js` | 62 | Autocomplete name-filter mirror: typo-tolerant matcher (Levenshtein-≤1 fallback) mirroring backend `folder_index_service.autocomplete()` |
| `hooks/useCytoscapeGraph.js` | 300 | Cytoscape lifecycle: init, drag (recomputes from frozen offsets), layout dispatch, L2 flow-only ↔ full toggle via `applyFlowVisibility` (pure .show()/.hide() — never re-layout) |
| `config/layout.js` | 49 | Layout constants (single source of truth) |
| `api/client.js` | 156 | API client + `errorDetail()` (L12; R23: `getWorkspaceInfo`/`scanWorkspace` wrappers removed) |

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
10. **L2 one-node-per-table (R22)**: compound table nodes are keyed by physical-table label (first occurrence = keeper); data flow may pass through a table multiple times via multiple edges. Aliases/subqueries/CTEs stay per-context. `_build_l2_graph` returns `search_matched` (False only when filtering was requested and no seed matched); the level2 response adds `search_matched: false` + `message` + full graph for not-in-flow scripts. Search matches a script only if it queries the searched field — `no_matches` + message otherwise, never fallback padding.
11. **S4b two-phase attribution (R22/M12–M15)**: plan → conflict-detect → apply; different-owner claims mark the field `ambiguous` (revoked, reported in `resolution_stats["ambiguous"]`); cache attribution is context-scoped; `GRAPH_CACHE_PREFIX` bumps invalidate pre-S4b graphs.
12. **Clean start (R23)**: the browser never auto-restores the previous workspace/search on load — the app mounts with an empty state (one-time `localStorage.removeItem('df_last_search_view')` purge for users of the old restore). `restoreViews.js` deleted.
13. **Single-script workspaces (R24)**: a folder with exactly one script still shows a full L1 — the script node + its tables + edges — clickable into L2. `_build_l1_graph` runs the full pipeline inline for single scripts (no bare-node shortcut), and `_filter_l1_by_lineage` never prunes the only script (`len(script_ids) > 1` guard).
14. **SUBSET edges never walkable (v3.3.138, B-series Phase 1)**: SUBSET is pure layout-padding — `EDGE_SEMANTICS[SUBSET] = {propagates_value: False, always_bidir: False}` removes it from `_BIDIR`. L2 field explosion (78 → 12 on the lending_ref audit) came almost entirely from SUBSET bridges pulling constants/partition columns/second-statement columns into the closure.
15. **Join-key expressions are nodes (v3.3.138, B-series Phase 2)**: JOIN ON CONCAT/RPAD/`||` expressions materialize as EXPRESSION vars (`defined_in="JOIN ON"`); the lineage JOIN rule admits expression neighbors unconditionally, all other JOIN partners on production evidence. Join keys are visible expression nodes in the full graph.
16. **Per-statement dedup (v3.3.138, C-9)**: extractor contexts are `TOP{stmt_idx}`; the L2 dedup key is `(parent_table_id, undecorated_label, stmt_idx)` — same-named fields in different statements no longer collapse (e.g. a JOIN key at TOP0 vs inside a CTE render as two fields). Known consequence: comparison-side join keys (own source only SCHEMA-reachable) render edge-less; DML edges into output tables drop with their SUBSET-severed producers (documented in the bug list, by design).
17. **S4b-consistent caches (v3.3.138, C-2/C-3/C-10)**: index no longer precomputes graph caches (they were pre-S4b and immediately stale); post-S4b it deletes all `graph_3_*.json`; every L2 miss path prefers the S4b-mutated `analysis_{cache_key}.json` and writes graph caches with `format_version = 3`. `GRAPH_CACHE_PREFIX` bumps invalidate older graphs. Existing workspaces need re-index after deploy for B-series/C-9 fixes.

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


18. **Highlights point at real lines (v3.3.139, D1/D2)**: `sql_line_mapper` skips comment
    lines when mapping expressions to lines; `_compute_highlight_ranges` drops `start<1`
    entries; cached line_maps are recomputed on read (`_recompute_line_map`) so stale
    pre-D1 caches render correct highlights without a cache-key bump.
19. **Scope-aware seed parenting (v3.3.139, B3/P1)**: `_resolve_scope_parent` scores
    candidates by scope distance (`_scope_distance`/`_pick_scope_candidate`); the search
    seed re-parents onto the searched table's own compound node (`is_target` pass);
    Sync 1 iterates all same-name alias instances and picks the first holding fields with
    the canonical source table. Seed fields keep their FILTER/JOIN edges at field level
    (P2 — no promotion for target seeds).
20. **C-4/C-5 gates (v3.3.139)**: persisted S4b apply counters move only when
    `n_attributed > 0` (mirror of the revoke-side `n_revoked > 0` gate); star expansion
    never resurrects revoked/ambiguous fields (excluded by
    `extractor_unresolved | ambiguous_fields`).
21. **Strict table.field flow (v3.3.140, L2 only)**: the L2 relevance filter uses
    `compute_field_flow` — the flow expands only where the searched table.field
    participates (FIELD_LIKE seeds, FIELD_LAND propagation, ALIAS/FILTER/JOIN zone
    rules, DML forward-only, owner resolution via source_tables[0]/qualifier label/
    unique same-context table-like var, container rule for CTE admission). The legacy
    table-level path (`filter_relevant`) stays byte-identical for L1 + legacy
    consumers. Seed fields appear on the physical node AND on alias/CTE/target nodes
    that carry the same field instance (P1 MOVE→COPY, all `is_target`); JOIN edges
    survive only when touching the seed zone (the mirror key column is a different
    field instance).
22. **Statement-anchored lines + single-line highlights (v3.3.140 → v3.3.145)**: the
    extractor records each statement's first-token line and resolves var positions
    within its own statement. **v3.3.145 (I1)**: definition-line resolution replaces
    the text-search patch layer (`_find_position_scoped` DELETED) — def lines come
    from the pre-tokenized stream (`self._tokens`, token `.line/.col`, 1-based),
    statement anchors from `_stmt_anchor_lines`; all vars are single-line
    `[L,L]` (line_end == line_start). Highlights = single `[line,line]` from
    node-carried `line_start` of the closure's field-like vars; `format_version` 4,
    cache prefix `graph_3_2_19`; verified byte-exact `[[18,18],[43,43],[158,158],[160,160]]`
    on BDM_ACC_LOAN_INFO_SUP_M.sql (253 vars / 649 deps: ALIAS 21→14, SUBSET 51→47,
    other 12 edge types identical to the v3.3.140 baseline). The raw walk no longer
    re-registers subquery-interior columns in outer contexts (phantom dedup: sample
    344→253 vars).
23. **Display strategies + parse-error diagnostics (v3.3.145)**: display is a
    separate module (`highlight_strategies.py`) that consumes extraction-time node
    info at render time — no cache impact for `single_line`/`label_only` (span
    strategies would need span fields + `format_version` 5, deferred). Extraction is
    the single source of truth for lines; strategy renderers never reconstruct
    positions. Parse failures (sqlglot) are recorded as `parse_errors` on the
    ExtractionResult, stamped into graph caches + level2 response, and rendered as a
    banner (reusing `.no-match-banner`) — never silently skipped, never auto-fixed
    (user ruling: report in the diagnostic panel, ask the human to fix).