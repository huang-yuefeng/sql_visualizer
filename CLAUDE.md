# CLAUDE.md — SQL Data Flow Visualizer

> Auto-generated snapshot for AI-assisted development. Update after major refactors.

## Project Overview

A **SQL data flow debugger** with 3-panel React frontend and FastAPI Python backend.
Parses SQL scripts → extracts variables + dependencies → renders interactive
Cytoscape.js data flow graphs (L1 cross-script pipeline, L2 per-script detail).

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker `gps-sql-backend` on port 8000
- **Frontend**: React 18 + Vite + Cytoscape.js, served from `frontend/dist/`
- **Tests**: vitest (frontend, 281 tests across 26 files, all green), pytest (backend, 1139 tests collected in `backend/tests/` — 1026 passed / 5 skipped / 108 failed, every failure an expected `test_l2_snapshot.py` rebaseline awaiting the unified regen; jaccard benchmark gate 20/20, all floors 1.0000)
- **Version**: See `/VERSION` (currently 3.3.190; the v3.3.191+ batch is staged in the working tree, pending release)
- **Service IP**: `192.168.0.66:8000` (never use `localhost`)

## File Map (Key Source Files)

### Backend (`backend/app/`)

| File | Lines | Role |
|------|-------|------|
| `routers/dataflow.py` | 535 | `GET /api/workspace/{ws_id}/views/{view_id}/level1`, `GET .../level2?script=&filter=`, `POST .../search`, view CRUD, `GET .../scripts/{name}/highlight` (R22: level1 lineage filter, base-index diagnostics). **K4 ruling 4**: `_normalize_direction` — omitted and legacy "upstream" both coerce to "downstream" at the boundary; only a value outside the allowlist returns 400 |
| `routers/workspace.py` | 437 | `/api/workspace` CRUD (DELETE: 400 malformed / 404 missing / 200 deleted), scan, index, filter-config, export-config, autocomplete. **#380 (2026-08-28)**: POST scan + index are creator-only (same rule as layout/filter-config #272 — participants get 403; a scan/index rewrites shared workspace state) |
| `routers/analysis.py` | 73 | Legacy `/api/analyze`, `/api/scripts`, `/api/analyze_multi` |
| `services/filter_service.py` | 531 | **Filter logic** (R19): CSV parse → scopes → A∩B intersection → filter application + diagnostics (F6); shared `resolve_script` (R5, path-containment-checked); F3/F4/F5 (COL_NAME-only rows dropped + `ignored_rows` counters, case folding) |
| `services/l1_builder.py` | 1136 | Cross-script L1 builder (production BFS → lineage_field_pairs → filter); M4-B degraded fallback (`degraded: true` + diagnostic); C2 single-cache-pass (R24: single-script workspaces run the full pipeline inline — script node + tables + edges, clickable to L2). **C-H1 (v3.3.160)**: `_lookup_analysis` — exact sql-keyed cache read requiring both extractor_version AND sql_text to match (edited-script stale analysis rejected) |
| `services/l2_builder.py` | 2169 | Per-script L2 builder; C1 split into named phases (`_build_edge_list`, `_simplify_dml_edges`, `_map_search_target_ids`, ...) — byte-identity-verified. **R22: one compound node per physical table** (label-keyed merge, `merged_original_ids`, `search_matched` in return dict). **#386 (2026-08-28, R5.12)**: MERGE targets join the physical fold (the model keys a MERGE target by raw name, roles {merge_target, read}) — table-duplication audit's one real bug; aliases stay out. **v3.3.138 (B-series)**: dedup key `(parent_table_id, undecorated_label, stmt_idx)` — B4 no `↻` twins, C-9 per-statement fields; `_resolve_scope_parent` context-segment walk (B3); label/table_name split for `⟐` (B5); `_load_or_build_graph` prefers S4b-mutated analysis caches (C-2b/C-10). **v3.3.139**: D2 `(0,0)` highlight filter + `_recompute_line_map` stale-cache defense; `_scope_distance`/`_pick_scope_candidate` scope-aware parenting + seed re-parent onto searched table (B3/P1); Sync 1 iterates all same-name aliases (p1 sync live); P2 target seed fields keep field-level edges. **v3.3.140 (strict table.field flow)**: `_apply_relevance_filter` switches to `filter_by_field_flow` (legacy `filter_relevant` kept for L1); highlights = single `[line,line]` from node-carried `line_start` of field-like closure vars (FIELD_LIKE_TYPES/PARTITION, D2 guard); P1 MOVE→COPY — seed copies (`seed_{id}_{keeper[:8]}`) land on alias/CTE/target nodes, all `is_target`; ctx-aware parent refinement (`_pick_scope_candidate`); Sync 1/2 stmt_idx-aware (C7); alias dedup key `(alias_parent_id, label, alias_line)` with `p1@29` display labels; JOIN edges survive only when touching the seed zone (seed-side JOIN only). **v3.3.145**: scope-context patch machinery deleted (`_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent`); `_compute_highlight_ranges` delegates to `get_strategy("single_line")`; `_load_or_build_graph` stamps `parse_errors` into graph caches. **v3.3.191+**: `_drop_partition_ddl_frames` (R43 — partition-DDL frames dropped display-only, right after the cache load); #387 write-target re-parenting when the SEARCH targets the write table (display projection); K4 ruling 1 — field chips carry `line_start` (line_start ONLY, keeper = first occurrence; `line_end` would re-route pickAutoEdge); R45 Fix H — the folded-edge carrier that names the keeper chip's own line wins over first-carrier-wins |
| `services/dataflow_service.py` | 780 | SearchView, view persistence (views.json, persists match_mode), edge style helpers (R22: no-matches search semantics, L2 `search_matched`/not-in-flow full-graph response; R24: single-script L1 never pruned by the disconnected-script rule; C-2b: miss path builds from analysis cache + writes graph cache format_version 3). **v3.3.140**: relevance filter via `filter_by_field_flow` (legacy `filter_relevant` re-export kept for sql_highlight_service), format_version 4 + `extractor_version` mismatch re-run. **v3.3.145**: `get_level2_graph(..., highlight_strategy="single_line")` + `?highlight_strategy=` query param (label_only → no highlights; unknown names fall back to single_line); `parse_errors` in level2 response (case-3 diagnostics). **v3.3.160**: L2 two-view field-flow closure — `flow_node_ids`/`flow_edge_ids` in the response plus byte-identical `full_graph` for the client-side flow-only ↔ full toggle; C-H1 exact sql-keyed analysis cache (md5 of `EXTRACTOR_VERSION|script|sql`). **v3.3.191+**: search resolves table/field through `resolve_name_ci` (the matched script set is the UNION over every case variant; the canonical spelling replaces the typed one on the view, the response and the L1/L2 builds — an unresolved name keeps the typed string); `_no_flow_result` (#400, banner-compatible `match_mode: "no_flow"`); the not-in-flow L2 message states the truthful reason ("not in the downstream flow of X — showing the full graph", replacing the factually wrong "the field is not queried in this script") |
| `services/folder_index_service.py` | 1556 | Folder scanning, script indexing, **A1 schema-file classification** (`file_class: schema\|script`), **S4b cross-script schema auto-resolution** (R22: two-phase plan→conflict-detect→apply, ambiguous fields revoked + `resolution_stats["ambiguous"]`, context-scoped cache attribution), resolution_stats aggregation, orphan report, index progress, `schema_evidence` in response. **F2 (audit #383, R2.9)**: defining-script invariant at 3 attribution sites — fields recorded from a script imply `table_index[t]["scripts"]`, so CTE entries (TEMP_RFN, temp_kmbh_*) are searchable. **v3.3.138 (C-series)**: CTAS→script (C-1), `_invalidate_graph_caches` post-S4b + index-time graph precompute REMOVED (C-2a), `_revoke_s4b_cache_update` (C-3), post-loop star expansion (C-5), `parse_by_script`/`parsed_cache` single parse (C-13a). **v3.3.139**: C-4 apply-side `n_attributed>0` gate; C-5 star expansion excludes revoked/ambiguous fields. **#245**: SELECT-output aliases (Fix A) + INSERT column names indexable for autocomplete (Bug 49 alias→physical, Bug 41 DML cross-ref); typo-tolerant matcher — substring primary, Levenshtein-≤1 fallback ranked exact > prefix > dist-1. **R2.11 (2026-08-29)**: `resolve_name_ci`/`scripts_for_name_ci` — the backend half of the F5 case-insensitive ruling: a typed name resolves to the canonical index key (the group of every case-variant), and the search intersection runs over the UNION of all variants' scripts, never one spelling's |
| `services/cache_keys.py` | 118 | `GRAPH_CACHE_PREFIX = "graph_3_2_25"` (single source of truth; `3_2_19` = v3.3.145 def-line/alias/containment, `3_2_25` = K4 ruling 3 paren-balance diagnostics — an INVALIDATION bump paired with `EXTRACTOR_VERSION 2026-08-28.7`, `format_version` stays 4) |
| `services/graph_service.py` | 326 | Cytoscape JSON builder, NODE_STYLES, EDGE_TYPE_STYLE/CATEGORY_MAP, table_fields/alias_map; `_stmt_idx_of` + context/stmt_idx in node data (C-9); `line_start`/`line_end` in node data (v3.3.140); copies `containment` onto graph edge data (v3.3.145, I5 — the flag must reach the walker/filter) |
| `services/highlight_strategies.py` | 268 | Display module (v3.3.145): `STRATEGIES` dict + `get_strategy(name)` — default `single_line` (node-carried `line_start`, D2 line-0 filter, adjacent-line merge), `label_only` → `[]`; unknown names fall back; extensible for future strategies (span etc.); R44 — `_anchor_line` anchors a WINDOW edge on the window application's own OVER line |
| `services/logger.py` | 183 | SSE pipeline logger (ref-counted queue cleanup) |
| `extractor/variable_extractor_v2.py` | 3657 | Role-based Identifier walking + S1–S6 orphan resolution; **S4a auto-attribution** (`_finalize_schema_candidates`, R6 field==table collision guard), statement-anchored loc (R22-L16: type-aware `_is_as_keyword` — string literals never the anchor; C-13b: token-position anchor), dict-of-dicts script_schemas; C4a unified stats (`resolved`/`unresolved_count`/`coverage_pct`). **v3.3.138**: contexts `TOP{stmt_idx}` (C-9), `_walk_join_key_expressions` (B-series Phase 2), label sanitation (B5). **v3.3.139**: order-independent join-key pairing (`_pair_join_key_sides`). **v3.3.140**: phantom dedup (`_explicitly_walked_selects` prune — subquery-interior columns registered once); statement-scoped line lookup (`_stmt_anchor_lines` + `_record_stmt_anchor` at `_walk_select/_walk_insert/_walk_merge/_walk_create`, `_find_position_scoped` — text-search expr[:40] within `[anchor, next_anchor)`, nested-context anchors excluded; `_add` uses it); PARTITION walk handles `exp.Column` + `exp.EQ`(Column left) on the Table node; `EXTRACTOR_VERSION = "2026-08-07.2"`. **v3.3.145 (I1/I2, definition-line resolution)**: vars carry DEF-site lines from the pre-tokenized stream (`self._tokens`, token `.line/.col`, 1-based) — `_find_position_scoped` text-search DELETED (patch layer); `_stmt_anchor_for(context)`; I2: `_register_column` sets `var.source_tables = [_resolve_alias(table, scope)]` (no early return — qualified columns attributed at extraction time); B3: `_attribute_output_containers` post-pass (CTE body outputs → own CTE, subquery/derived outputs → own VIRTUAL_TABLE); records `parse_errors` on ExtractionResult (case-3); `EXTRACTOR_VERSION = "2026-08-08.1"`. **R44/R45 (2026-08-28, LANDED — pending release)**: occurrence-side field registration — families 1/2 write-side + derived-read twins, family 3 occurrence-line twins for `_add`-collapsed 2nd..Nth occurrences (`_collapsed_occurrences` + `_register_flow_occurrence_twins`; Fix C: the occurrence-line search is bounded by the group's own paren scope `_paren_scope_bound` and never claims a line a nested scope owns `_scope_line_owner`; Fix D: `_base_var_for` matches the group's FULL casefolded identity; Fix E/F/G: per-clause line pairing `_line_clauses`/`_occurrence_clause`, spelling-insensitive `taken` computed once, a bare identity only matches BARE token occurrences), `_register_groupby_twins` GROUP-BY twins, K3 expression-fragment guard. **K4 ruling 3**: `_paren_balance_errors` — structural paren-balance diagnostics, ONE tokenizer pass over the original script split at `;` tokens. `EXTRACTOR_VERSION = "2026-08-28.8"` |
| `extractor/dependency_graph.py` | 981 | VariableDefinition → VariableDependency (16 edge types); Phase 6b JOIN-key expression edges + REF classification (B-series Phase 2). **v3.3.145 (I3/I4)**: Phase 2 ALIAS = one edge per `alias_of` exact source-var id (name-matching cross-product DELETED; `id_index`/`var_order` support); Phase 7/8 anchors via `_pick_anchor` (candidates `_TABLE_TYPES` with `0 < line_start <= v.line_start`, max line, ties: empty `source_tables` > non-VIRTUAL_TABLE > registration order; `_parent_ctx` ancestor walk; global first-match DELETED; no candidate → skip); Phase 4b tags SCHEMA container→nested ⟐VT edges `containment=True` (I5). **R44/R45 (2026-08-28)**: Phase 4d-gb emits the SCHEMA belongs-to edge for GROUP-BY/occurrence twins (the twin's qualifier is its physical owner, so Phase 4d's prefix match misses it and Phase 8's bridge alone leaves it disconnected — topology check "no connection from source table"); `_twin_group_admits` admits a family-3 twin whose group collected a clause its own label lost |
| `extractor/sql_line_mapper.py` | 86 | SQL expression → line mapping for `highlights` (D1: comment lines skipped, v3.3.139). **v3.3.140**: prefers var-carried `line_start`/`line_end` (statement-scoped) when > 0; text search kept as stale-cache fallback |
| `extractor/lineage.py` | 1771 | `compute_field_lineage()`, `filter_relevant()` (R18). **R44 (LANDED, 2026-08-28 — pending release)**: occurrence-coverage admission rounds in `compute_field_flow`, all additive (user ruling "flow-only must cover all occurrences") — R0 case-insensitive entity match, R1 write-completion (a constant projection's output VT is admitted so the write leg renders), R3 derived-product admission (a var carrying the field part whose holder reads the searched table in its own scope is an occurrence), #399 option b′ (the searched table part may name a SQL ALIAS — union the alias's owning entities, gated on no entity hosting the field). **v3.3.138 (B-series Phase 1)**: SUBSET `{propagates_value: False, always_bidir: False}` — never walkable; JOIN rule admits expression nodes unconditionally, others on production evidence; None-guards. **v3.3.140**: `compute_field_flow()`/`filter_by_field_flow()` — strict table.field walker (FIELD_LIKE/FIELD_LAND/NEVER sets; ALIAS iff source_tables[0]==target; FILTER/JOIN iff seed-zone endpoint; DML forward-only; owner resolution + container rule; identity admissions to fixpoint) — legacy functions byte-identical. **v3.3.145 (I5)**: containment edges excluded — `_is_containment(ed)` helper (dict-key + object-attr forms), skipped in `compute_field_flow` adjacency + `filter_by_field_flow` output |
| `extractor/schema_inference.py` | 180 | `infer_table_schemas()` — 7-pass iterative stabilization |
| `models/variable.py` | 127 | VariableType enum (16 types), VariableDefinition, VariableDependency; `VariableDefinition.alias_of` (I4: exact source var id for ALIAS edge) + `VariableDependency.containment` (I5) |
| `models/sql_model.py` | 161 | Canonical taxonomy: node↔edge types mapped to SQL |
| `main.py` | 295 | FastAPI app init + router mount; `_VersionedStatic` static mount (v3.3.190 cache headers — index.html/no-asset paths `no-cache`, content-hashed `assets/*` `immutable`) |

### Frontend (`frontend/src/`)

| File | Lines | Role |
|------|-------|------|
| `DataFlowApp.jsx` | 696 | Data Flow Debugger main component (search, view persistence, resolution report, `schema_evidence` state; R22: `applyL2Result` + L2 not-in-flow banner, L1 no-matches message banner; R23: no browser auto-restore — clean start on load, one-time `df_last_search_view` purge). **v3.3.191+**: #400 — the no-flow banner carries an "Open <script> full graph" button (a no-flow search matches scripts but its L1 is empty, so there was no UI path to them); a not-in-flow strip lists the scripts outside the flow, each clickable into its full L2; F-B2 `sqlLineNotice` — a line-0/absent `line_start` shows "this element has no SQL line" instead of silently clearing the previous highlight |
| `App.jsx` | 857 | SQL Analysis (legacy single-script) |
| `components/DataFlowGraph.jsx` | 306 | Cytoscape renderer (no edge-hover tooltip — removed #240) |
| `components/SqlPanel.jsx` | 329 | SQL display + syntax highlighting |
| `components/FilterPanel.jsx` | 345 | Filter upload UI + warning banner (R2), renders `ignored_rows`; F5 (audit #383): canonical-key echo + inline "no such table.field in the index" message replacing the silent no-op; F-B2 — an autocomplete dropdown renders only while the typed name does NOT yet resolve AND its option list is non-empty (a resolved name leaves no overlay to cover or click-block the next input; typing never spawns an empty dropdown) |
| `components/ResolutionReport.jsx` | 99 | Orphan resolution coverage badge + breakdown (R20) |
| `components/WorkspacePanel.jsx` | 75 | Workspace upload/scan/index UI |
| `components/FieldStoryBar.jsx` | 130 | Field Story step-through bar (v3.3.188, R40.3): numbered step chips, ◀/▶, autoplay 3s, ✕ dismiss — presentational, ALL state in DataFlowApp; relocated below the SQL panel (v3.3.189) |
| `utils/layoutCore.js` | 244 | Shared layout: `fieldPositionsForTable()`, `positionTableFields()`, `applyLayout()` |
| `utils/snakeLayout.js` | 107 | Snake/wrapping layout |
| `utils/elkLayout.js` | 239 | ELK layered layout |
| `utils/resolutionReport.js` | 93 | Stats normalization (prefers unified `unresolved_count`/`coverage_pct`) |
| `utils/flowVisibility.js` | 322 | L2 two-view toggle helper: resolves initial flow-only state and applies `.show()/.hide()` visibility from `flow_node_ids`/`flow_edge_ids` (never re-layout — positions preserved across toggles). v3.3.183–190 merged-view filter chrome: synthetic `⟂` caption nodes + table-border loop-line (`capA_/capB_/capL_<edgeId>` via `upsertFilterCaptions`, zoom-compensated caption font) + `centerOnSeed` post-toggle re-center. v3.3.191+: data-driven `loopstep` per self-edge (`halfWidth + 150`) for `control-point-step-size` (R40.8 — the real self-loop geometry knob); R41 `recenter:false` on user-initiated Fit. **V2-N1 (2026-08-29)**: the searched `is_target` seed chips are EXEMPT from the merged-view zero-edge chip hiding — they are the chips the user searched for (5 of 7 measured closures otherwise rendered zero chips in the default Flow-only view) |
| `utils/fieldStory.js` | 432 | Field Story derivation (v3.3.188, R40.3): the searched field's closure as ordered steps birth→written→read→**joined**→filtered→consumed (Joined/Transformed added v3.3.191, R40.10 — 6 stages, user-authorized ≤10) — PURE projection of the served payload; each step carries BOTH edge-id namespaces (detailed `l2e_*` + merged `l2m_*` via `mergedEdgeIds`) |
| `utils/nameFilter.js` | 90 | Autocomplete name-filter mirror: typo-tolerant matcher (Levenshtein-≤1 fallback) mirroring backend `folder_index_service.autocomplete()`; F5 (audit #383): `resolveNameCi()` case-insensitive resolution to the canonical index key |
| `hooks/useCytoscapeGraph.js` | 512 | Cytoscape lifecycle: init, drag (recomputes from frozen offsets), layout dispatch, L2 flow-only ↔ full toggle via `applyFlowVisibility` (pure .show()/.hide() — never re-layout). R41 (v3.3.191+): `minZoom` 0.08 + Fit passes `recenter:false`; `CY_CORE_OPTIONS` exported (frozen shared core options: `wheelSensitivity` 0.3, `minZoom` 0.08, `maxZoom` 5) |
| `config/layout.js` | 49 | Layout constants (single source of truth) |
| `api/client.js` | 156 | API client + `errorDetail()` (L12; R23: `getWorkspaceInfo`/`scanWorkspace` wrappers removed). **K4 ruling 4**: `searchDataFlow` defaults `direction='downstream'`, so an omitted argument cannot re-introduce the upstream contract the API no longer honors |

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
    cache prefix `graph_3_2_19` (since bumped to `graph_3_2_25`); verified
    byte-exact `[[18,18],[43,43],[158,158],[160,160]]`
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
    (user ruling: report in the diagnostic panel, ask the human to fix). **K4
    ruling 3 (2026-08-28)**: ErrorLevel.IGNORE recovers a partial tree from
    almost anything, so a statement whose parens never close parsed into a
    plausible graph with a clean `parse_errors: []` — a structural
    paren-balance check (`_paren_balance_errors`) now runs ONE tokenizer pass
    over the original script (string/comment aware), splits at `;` TOKENS and
    records every statement still holding `(` open at its end. Diagnostics
    only: extraction never rejects; the detail says the recovered tree may be
    incomplete.
24. **Dynamic hover label emphasis (v3.3.171–177)**: hovering a node enlarges its
    label plus every field chip of its box (chips are top-level nodes linked by
    `_tableParent` — `children()` is always empty); hovering an edge enlarges both
    endpoints AND their chips. Pure display: `.label-emph` composed LAST in the
    cytoscape sheet, per-tier 2× sizes (titles 24, chips 20), classes never feed
    layout. `minZoom` floor was 0.28 (0.05 made any multiplier sub-pixel) — superseded
    by #42/R41: floor 0.08 + `min-zoomed-font-size` font gate.
25. **Fit spends the window on content (v3.3.172/175/177)**: `FIT_PADDING=24`,
    L2 small-panel adaptive floor 16px/5% — kept in sync in BOTH
    `useCytoscapeGraph` and `layoutCore.applyLayout` (initial-fit path).
26. **View-open search-params recovery (v3.3.178)**: clicking an L1/L2 view in the
    tree restores its `table`/`field` into the search panel via
    `recoverViewSearch` (row or `parent_view_id` search row; null → panel
    untouched, never guessed). R23 clean-start on page load is untouched.
27. **Release pipeline ships the current frontend (v3.3.174, R36)**: the image
    serves PREBUILT `backend/app/static/`; `release.sh` stage 0.5 rebuilds the
    frontend, stamps VERSION into dist/index.html, and syncs `dist → static`
    before docker build. Deployment truth-test = artifact hash parity (local
    dist sha256 == deployed sha256), never commit history — v3.3.177's race
    shipped a stale bundle while history looked inclusive.
29. **Direction toggle removed — downstream only (v3.3.180, R38 ruling;
    K4 ruling 4, 2026-08-28 closes the API)**: the
    Upstream/Downstream switch in the search panel is gone; every search (and
    every L2 fetch) runs downstream. The `direction` parameter is accepted
    but never honored — an omitted value AND a legacy "upstream" coerce to
    "downstream" at the router boundary (`_normalize_direction`); only values
    outside {upstream, downstream} return 400. One direction, one mental
    model: "where does this field's value go" — provenance questions remain
    answerable in the full view. (The upstream walker machinery below the
    router is untouched — API-unreachable; retirement is a future work item.)
30. **Merged self-loop filter labels + flow-line invariants (v3.3.181, R39)**:
    R32 promotion turns absorbed FILTER edges into unlabeled self-loops; the
    frontend re-attaches `⟂ <fields> (filtered @L<line>)` client-side
    (`selfLoopFilterLabels` over the detailed closure; backend payloads
    untouched). Two standing gates in `test_flow_line_invariants.py`: INV-1
    every DML field-line has ≥1 closure edge (DDL ADD PARTITION lines are the
    documented exception — new coverage there fails the test); INV-2 every
    closure edge carries a SQL line.
28. **L2 node click → SQL definition line (v3.3.179, R37)**: tapping a node
    feeds its `data.line_start` into the SINGLE `sqlHighlightLine` channel
    (shared with edge clicks; last wins; `SqlPanel` unchanged). Line
    semantics = server contract: field chip → its variable's I1 definition
    line (keeper = first occurrence; chips carry `line_start` and never
    `line_end` — an endpoint pair would re-route pickAutoEdge's priority-1
    seed-zone pick); ⟐ VT → its creation line (top-level VT: the DML/SELECT
    statement's own first token — never the WITH line; nested
    subquery/derived/EXISTS VT: the body's first output line, falling back to
    the body's SELECT head); physical table → first occurrence; alias/CTE →
    FROM/JOIN line. Guards: integer `≥1` else
    silent no-op (TVF alias `f`@L0 no-ops until M-T1), first line only, L2
    only, own-payload lookup (never label matching).
31. **Field Story step-through (v3.3.188, R40.3)**: the searched field's L2
    closure re-told as an ordered story — birth → written → read → filtered →
    consumed. Pure client-side projection (`utils/fieldStory.js` — no React,
    no cytoscape, no SQL text, nothing guessed): seed = case-insensitive
    field-node match on the physical-table compound (#288 folding); only
    closure edges with a valid `highlight_line` (INV-2) participate;
    first-match-wins classification (birth outranks read — the binding edge
    is read-shaped but sits at the table's anchor line); steps group per
    (kind, line), kind-first / line-ascending. Each step carries BOTH edge-id
    namespaces — detailed `l2e_*` AND merged content-derived `l2m_*`
    (`mergedEdgeIds` resolved against `full_merged` by highlight_line +
    parent-promoted endpoint pair) — without this, story emphasis silently
    no-ops in the default merged view. Stepping reuses the single R37
    `sqlHighlightLine` channel and dims non-involved elements (`story-dim`
    0.15, the cone-dim convention); `STORY_STYLES` is appended to the LIVE
    stylesheet by DataFlowGraph so it composes last and wins specificity
    ties. Red-team rulings A1–A10 folded. The bar
    (`components/FieldStoryBar.jsx`) is presentational — ALL state lives in
    DataFlowApp.
32. **Flow-reason panel removed (v3.3.189, R40.4 — user ruling)**:
    `EdgeReasonPanel` is deleted; the FieldStoryBar sits in its slot below
    the SQL panel. The filter step lights the synthetic loop-line + caption
    chrome (f648: the underlying edge renders ~0px — coincident field→
    own-table endpoints; merged self-loop ~7px), under a GUARD rule:
    story-active may only GROW the loop-line (`edge.filter-loopline.
    story-active` width 9 beats the generic 5, which would shrink the 7px
    chrome); the caption golds (`#FFD700`).
33. **Cache headers (v3.3.190, R40.6)**: `_VersionedStatic` in
    `backend/app/main.py` — non-asset responses (index.html)
    `Cache-Control: no-cache` (ETag still gives 304s); content-hashed
    `assets/*` `public, max-age=31536000, immutable`. Root cause of the
    recurring "deployed but user sees old UI" reports: absent Cache-Control,
    browsers applied RFC 7234 heuristic freshness (~10% × age) to index.html
    and kept serving a whole old bundle — the client-side twin of R36's
    stale-static race (hash-parity remains the truth-test).
34. **History slim (v3.3.190+, R40.7)**: repo history filter-rewritten,
    1.21GiB → ~150MB clone. Every existing clone must RE-CLONE (old remotes
    point at orphaned pre-rewrite history); image pieces re-committed at HEAD
    with a re-stamped manifest.
35. **L2 initial layout left-to-right (v3.3.190+, R42)**: the L2 graph opens
    in the ELK pipeline layout (layered, direction RIGHT — landscape flow:
    sources left, targets right); snake remains a manual toolbar option on
    BOTH L1 and L2. Per-level layout state (`l1LayoutMode` default 'snake',
    `l2LayoutMode` default 'pipeline' in `DataFlowApp.jsx`) — L1's default is
    untouched. Fields never move with the layout choice: layout algorithms
    emit table coordinates only, field positions derive from
    `table.pos + frozen offsets` (single site in `layoutCore.js`). L2 layout
    persistence is keyed per view family (M-E1): merged views save under
    `l2:merged:{script}`, detailed under `l2:{script}` — a drag in one mode
    never pins the other; the backend script key is free-form, no schema
    change.
36. **Partition-DDL frames dropped from L2 (R43, user ruling 2026-08-28)**:
    `ALTER TABLE … ADD/DROP/MSCK PARTITION` statements never appear in the
    L2 graph — "folder names, not dataflow." `_drop_partition_ddl_frames`
    (l2_builder) removes each such statement's ⟐ output VT + its edges right
    after the graph-cache load and before the flow filter — full AND flow
    views, display-layer ONLY (extraction/TOPn indexing, EXTRACTOR_VERSION
    and graph-cache format untouched: the cache keeps extraction truth, the
    display projects it, so pre-R43 caches stay valid — no prefix bump).
    Detection is conservative (statement text from the VT's own line_start
    must open `ALTER TABLE` and carry an ADD/DROP/MSCK … PARTITION clause);
    CREATE TABLE/SET/column-DDL stay. EAST5 full L2 129→119 nodes /
    168→148 edges; flow closures unchanged. Snapshot regeneration pending
    (test_l2_snapshot expected to fail until the unified rebaseline).
37. **Field Story Joined/Transformed stage (R40.10, 2026-08-28 — pending
    release)**: a 6th stage (user-authorized ≤10) — edges of type
    JOIN/TRANSFORM/COMPUTED/WINDOW/AGGREGATE touching the seed/table are
    told as their own step, ordered between Read and Filtered
    (`KIND_RANK` birth/written/read/joined/filtered/consumed, label
    "Joined/Transformed"); SCHEMA/ALIAS/SUBSET stay non-narrative by
    design. Evidence: random-10 field audit — 49 previously-unclassified
    narrative edges left source-side fields at 1–2 steps; +30 projected
    steps across 7/10 fields.
38. **MERGE targets join the physical fold (R5.12, #386, 2026-08-28)**:
    the table-duplication audit's ONE real bug — a table MERGE-INTO'd in
    one statement and read/written in another rendered as TWO compound
    nodes. The model already keys a MERGE target by its raw name (kind
    physical, roles {merge_target, read}), so `l2_builder`'s fold admits
    merge_target occurrences (2 conditions; aliases excluded); +3 T3
    regression tests. Adversarial cases prove schema/backtick/case twins
    were already folded and 1-char-apart tables never over-merge. Four
    #386 rulings filed (CTE-shadows-physical stays separate; RFN typo
    pairs are real distinct tables; RFN duplicated INSERT block is
    deliberate sample content; alias-label collisions informational).
39. **CTE index defining-script invariant (F2, audit #383, R2.9)**: CTE
    `table_index` entries received fields but never the defining script,
    so the search intersection `field_index[f].scripts ∩
    table_index[t].scripts` was empty and qualified CTE lookups
    (TEMP_RFN, temp_kmbh_*) found nothing. Invariant now installed at 3
    attribution sites in `folder_index_service.py`: fields recorded from
    a script imply `table_index[t]["scripts"].add(rel_path)`. The
    unqualified-only CTE ruling is preserved. +6 tests
    (`test_folder_index_cte.py`), 128 regressions green.
40. **Case-insensitive name resolution (F5, audit #383, R2.10)**: SQL
    identifiers are case-insensitive but index keys carry whatever casing
    each script wrote (TEMP_RFN vs temp_rfn) and the backend matches keys
    exactly. `resolveNameCi()` (`utils/nameFilter.js`) resolves a typed
    name in any casing to the canonical index key (exact key wins;
    case-insensitive equals ranked with the dropdown's collation —
    deterministic); the FilterPanel echoes the canonical key and shows an
    inline "no such table.field in the index" message on a null
    resolution — replacing the silent no-op. +10 tests.
41. **Self-loop curve geometry — the real knob (R40.8, 2026-08-28)**: the
    v3.3.185 "segments" enlargement never rendered — `segment-points` is
    not a cytoscape 3.34 property (segments are driven by
    `segment-weights`/`segment-distances`; the parsed stylesheet silently
    drops it) and a self-edge always routes through `findLoopPoints`
    whatever `curve-style` says. The real levers are the loop properties:
    `control-point-step-size: data(loopstep)` with `flowVisibility.js`
    sizing each self-edge's `loopstep` from its endpoint box
    (`halfWidth + 150`); the dead segp/segments bracket machinery was
    removed. Clicking the curve highlights its SQL line (DOM-verified,
    L190); the Filtered story step grows the curve under the width-9
    guard.
42. **Overview zoom + Fit correctness (R41, 2026-08-28 — amends #24)**:
    `minZoom` 0.28 → 0.08 plus `min-zoomed-font-size: 6` — below
    legibility labels HIDE instead of smearing (boxes-only overview, user
    ruling); legibility moved OFF the zoom clamp ONTO the font gate.
    User-initiated Fit passes `recenter: false` through
    `fitAllElements` so `centerOnSeed` no longer re-centers after the
    Fit (view-mode toggles keep the default recenter). Audit: fit wanted
    0.08–0.09 vs the 0.28 floor — 87/129 nodes hidden; floor-lift probe
    129/129 visible.
43. **R44 walker occurrence coverage — LANDED, pending release (user
    ruling 2026-08-28; R45 family 3 included)**: "flow-only must cover
    all occurrences" — the 30-case audit's ~50% coverage / 17 walker
    misses in 5 classes (constant writes, rename-writes, predicates/
    window keys, derived passthrough, cross-statement asymmetry) are
    addressed by occurrence-side twins (`_register_flow_occurrence_twins`
    — families 1/2 write-side + derived-read, family 3 occurrence-line
    twins for `_add`-collapsed 2nd..Nth occurrences, paren-scope bounded
    via `_paren_scope_bound`/`_scope_line_owner` with per-clause line
    pairing), `_register_groupby_twins`, OVER-line WINDOW anchors
    (`highlight_strategies._anchor_line`), Phase 4d-gb SCHEMA belongs-to
    edges, and the additive admission rounds in `lineage.py`; wrong-
    owner/scope/clause fixes C/D/E/F/G fold into
    `EXTRACTOR_VERSION 2026-08-28.8`. Benchmark re-derived: jaccard gate
    20/20, every floor 1.0000 (recall AND precision). The unified L2
    snapshot regeneration is the remaining step (R44.3, still ⏳ —
    snapshot failures are expected rebaselines). Row-level record:
    `wiki/REQUIREMENTS_TRACEABILITY.md` §"R44".