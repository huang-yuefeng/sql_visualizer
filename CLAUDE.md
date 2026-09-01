# CLAUDE.md — SQL Data Flow Visualizer

> Auto-generated snapshot for AI-assisted development. Update after major refactors.

## Project Overview

A **SQL data flow debugger** with 3-panel React frontend and FastAPI Python backend.
Parses SQL scripts → extracts variables + dependencies → renders interactive
Cytoscape.js data flow graphs (L1 cross-script pipeline, L2 per-script detail).

- **Backend**: FastAPI + sqlglot (MySQL dialect), Docker `gps-sql-backend` on port 8000
- **Frontend**: React 18 + Vite + Cytoscape.js, served from `frontend/dist/`
- **Tests**: vitest (frontend, **438 tests across 34 files**, all green), pytest (backend, current gate **1551 passed / 11 skipped / 0 failed / 0 deselected / 0 xfailed** — the `release.sh` deselect list is **EMPTY at all three of its pytest sites** since v3.3.197: both R29 ruled-red doc tests went GREEN under the 2026-09-01 §7-A ruling, and the list is KEPT EMPTY by rule — it reopens only for a test that is red-documented PENDING a ruling, see #57). Jaccard benchmark gate **20/20 at 1.0000/1.0000 recall AND precision** (set equality, both directions — the two former ruled-red `lending_ref` cases are GREEN since the R46c/R46d canonical re-derivation, #55). L2 snapshots: **108 committed baselines, all green** — the last rebaseline was the v3.3.197 wave (103 files re-pinned, commit `6001ef9`; content sets identical, keeper re-picks rehash ids only)
- **Version**: See `/VERSION` (**3.3.197 RELEASED 2026-09-02**, release commit `6c2ed1c`, deployed to prod and pushed to `origin/main`; `6001ef9` is the feature commit). The wave is **LANDED, not staged**: V4 walker batch, V5 occurrence twins, V6 model persistence (`graph_service.py` `MODEL_CACHE_*`, `cache/model_{key}.json`), V7 walker-admission fixes g1/d2 (`lineage.py`), V8 walker determinism (`_WALK_RANK` + the 5-seed byte-identity HARD gate, #58), rule 3a reversal + `_prune_orphan_sibling_chips` (#58), §7-A write-leg-only (#57), M-T1 TVF alias anchors (`skip_parens`), H11 Phase 4d-gc MERGE/predicate belongs-to edges, X1 deterministic PROVENANCE + guard 3b, J1 field-involvement + J2 fold ownership, H12 model-build perf, R31.35 file-driven user management. `EXTRACTOR_VERSION = "2026-08-28.13"`
- **Service IP**: `192.168.0.66:8000` (never use `localhost`)

## File Map (Key Source Files)

### Backend (`backend/app/`)

| File | Lines | Role |
|------|-------|------|
| `routers/dataflow.py` | 639 | `GET /api/workspace/{ws_id}/views/{view_id}/level1`, `GET .../level2?script=&filter=`, `POST .../search`, view CRUD, `GET .../scripts/{name}/highlight` (R22: level1 lineage filter, base-index diagnostics). **K4 ruling 4**: `_normalize_direction` — omitted and legacy "upstream" both coerce to "downstream" at the boundary; only a value outside the allowlist returns 400. **P1 catch-up gate (v3.3.194)**: the index-derived endpoints (`POST .../search`, the second index-derived route) refuse with a retry-able **409** "Index is being updated for this workspace — retry in a moment" while `is_index_catching_up(ws_id)` — answering from the previous index would return a false "not queried by any script" for a field that exists only in a just-added script. **MSC-3**: `search` and `l2_opened` are recorded in the bounded activity trail |
| `routers/workspace.py` | 628 | `/api/workspace` CRUD (DELETE: 400 malformed / 404 missing / 200 deleted), scan, index, filter-config, export-config, autocomplete. **#380 (2026-08-28)**: POST scan + index are creator-only (same rule as layout/filter-config #272 — participants get 403; a scan/index rewrites shared workspace state). **#380 follow-up (AD2-A, v3.3.194)**: `GET .../tree` + `GET .../index` are the participant READ half of Open — they serve the PERSISTED artifacts (`cache/file_tree.json`, the two index JSONs + `index_report.json` + the `freshness` content diff + the `catching_up` flag), never re-scan and never rebuild; missing/corrupt cache → 409 / `{}`, never 500, no membership side effect. **MSC-3**: `_audit` funnels `workspace_created` / `visit_start` / `layout_saved` / `visit_end` / `scan` / `index` into the bounded per-workspace activity trail (close is recorded as `visit_end`) |
| `routers/analysis.py` | 92 | Legacy `/api/analyze`, `/api/scripts`, `/api/analyze_multi` |
| `services/filter_service.py` | 531 | **Filter logic** (R19): CSV parse → scopes → A∩B intersection → filter application + diagnostics (F6); shared `resolve_script` (R5, path-containment-checked); F3/F4/F5 (COL_NAME-only rows dropped + `ignored_rows` counters, case folding) |
| `services/l1_builder.py` | 1370 | Cross-script L1 builder (production BFS → lineage_field_pairs → filter); M4-B degraded fallback (`degraded: true` + diagnostic); C2 single-cache-pass (R24: single-script workspaces run the full pipeline inline — script node + tables + edges, clickable to L2). **C-H1 (v3.3.160)**: `_lookup_analysis` — exact sql-keyed cache read requiring both extractor_version AND sql_text to match (edited-script stale analysis rejected) |
| `services/l2_builder.py` | 3022 | Per-script L2 builder; C1 split into named phases (`_build_edge_list`, `_simplify_dml_edges`, `_map_search_target_ids`, ...) — byte-identity-verified. **R22: one compound node per physical table** (label-keyed merge, `merged_original_ids`, `search_matched` in return dict). **#386 (2026-08-28, R5.12)**: MERGE targets join the physical fold (the model keys a MERGE target by raw name, roles {merge_target, read}) — table-duplication audit's one real bug; aliases stay out. **v3.3.138 (B-series)**: dedup key `(parent_table_id, undecorated_label, stmt_idx)` — B4 no `↻` twins, C-9 per-statement fields; `_resolve_scope_parent` context-segment walk (B3); label/table_name split for `⟐` (B5); `_load_or_build_graph` prefers S4b-mutated analysis caches (C-2b/C-10). **v3.3.139**: D2 `(0,0)` highlight filter + `_recompute_line_map` stale-cache defense; `_scope_distance`/`_pick_scope_candidate` scope-aware parenting + seed re-parent onto searched table (B3/P1); Sync 1 iterates all same-name aliases (p1 sync live); P2 target seed fields keep field-level edges. **v3.3.140 (strict table.field flow)**: `_apply_relevance_filter` switches to `filter_by_field_flow` (legacy `filter_relevant` kept for L1); highlights = single `[line,line]` from node-carried `line_start` of field-like closure vars (FIELD_LIKE_TYPES/PARTITION, D2 guard); P1 MOVE→COPY — seed copies (`seed_{id}_{keeper[:8]}`) land on alias/CTE/target nodes, all `is_target`; ctx-aware parent refinement (`_pick_scope_candidate`); Sync 1/2 stmt_idx-aware (C7); alias dedup key `(alias_parent_id, label, alias_line)` with `p1@29` display labels; JOIN edges survive only when touching the seed zone (seed-side JOIN only). **v3.3.145**: scope-context patch machinery deleted (`_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent`); `_compute_highlight_ranges` delegates to `get_strategy("single_line")`; `_load_or_build_graph` stamps `parse_errors` into graph caches. **v3.3.191+**: `_drop_partition_ddl_frames` (R43 — partition-DDL frames dropped display-only, right after the cache load); #387 write-target re-parenting when the SEARCH targets the write table (display projection); K4 ruling 1 — field chips carry `line_start` (line_start ONLY, keeper = first occurrence; `line_end` would re-route pickAutoEdge); R45 Fix H — the folded-edge carrier that names the keeper chip's own line wins over first-carrier-wins. **v3.3.195 wave (shipped)**: `_apply_field_involvement` (J1, decision #48) admits a served edge only when the searched field is involved in the data flow — Class 1: a JOIN carrier only at a JOIN-ON line (`line_clause_map`), Class 2: never a sibling field's value legs; the multi-anchor fold (G8/RC-B) keys `(source, target, edge_type, anchor)` so K anchors serve K edges instead of going dark on N−1; and the model read ladder is analysis cache → the PERSISTED `model_{key}.json` alias truth → the cached graph (FSC-2, decision #50). **v3.3.197**: `_apply_field_involvement` **Class 3** (rule 3a REVERSED) drops a sibling's belongs-to edge and `_prune_orphan_sibling_chips` prunes the sibling chips the drop leaves edge-less — flow-only views only, the full view is byte-untouched (decision #58) |
| `services/dataflow_service.py` | 901 | SearchView, view persistence (views.json, persists match_mode), edge style helpers (R22: no-matches search semantics, L2 `search_matched`/not-in-flow full-graph response; R24: single-script L1 never pruned by the disconnected-script rule; C-2b: miss path builds from analysis cache + writes graph cache format_version 3). **v3.3.140**: relevance filter via `filter_by_field_flow` (legacy `filter_relevant` re-export kept for sql_highlight_service), format_version 4 + `extractor_version` mismatch re-run. **v3.3.145**: `get_level2_graph(..., highlight_strategy="single_line")` + `?highlight_strategy=` query param (label_only → no highlights; unknown names fall back to single_line); `parse_errors` in level2 response (case-3 diagnostics). **v3.3.160**: L2 two-view field-flow closure — `flow_node_ids`/`flow_edge_ids` in the response plus byte-identical `full_graph` for the client-side flow-only ↔ full toggle; C-H1 exact sql-keyed analysis cache (md5 of `EXTRACTOR_VERSION|script|sql`). **v3.3.191+**: search resolves table/field through `resolve_name_ci` (the matched script set is the UNION over every case variant; the canonical spelling replaces the typed one on the view, the response and the L1/L2 builds — an unresolved name keeps the typed string); `_no_flow_result` (#400, banner-compatible `match_mode: "no_flow"`); the not-in-flow L2 message states the truthful reason ("not in the downstream flow of X — showing the full graph", replacing the factually wrong "the field is not queried in this script"). **v3.3.195 wave (shipped)**: the L2 model read ladder (FSC-2) is analysis cache → persisted `cache/model_{key}.json` alias truth → cached graph, and the graph-cache write path also writes the model artifact (decision #50) |
| `services/folder_index_service.py` | 2419 | Folder scanning, script indexing, **A1 schema-file classification** (`file_class: schema\|script`), **S4b cross-script schema auto-resolution** (R22: two-phase plan→conflict-detect→apply, ambiguous fields revoked + `resolution_stats["ambiguous"]`, context-scoped cache attribution), resolution_stats aggregation, orphan report, index progress, `schema_evidence` in response. **F2 (audit #383, R2.9)**: defining-script invariant at 3 attribution sites — fields recorded from a script imply `table_index[t]["scripts"]`, so CTE entries (TEMP_RFN, temp_kmbh_*) are searchable. **v3.3.138 (C-series)**: CTAS→script (C-1), `_invalidate_graph_caches` post-S4b + index-time graph precompute REMOVED (C-2a), `_revoke_s4b_cache_update` (C-3), post-loop star expansion (C-5), `parse_by_script`/`parsed_cache` single parse (C-13a). **v3.3.139**: C-4 apply-side `n_attributed>0` gate; C-5 star expansion excludes revoked/ambiguous fields. **#245**: SELECT-output aliases (Fix A) + INSERT column names indexable for autocomplete (Bug 49 alias→physical, Bug 41 DML cross-ref); typo-tolerant matcher — substring primary, Levenshtein-≤1 fallback ranked exact > prefix > dist-1. **R2.11 (2026-08-29)**: `resolve_name_ci`/`scripts_for_name_ci` — the backend half of the F5 case-insensitive ruling: a typed name resolves to the canonical index key (the group of every case-variant), and the search intersection runs over the UNION of all variants' scripts, never one spelling's. **P1 (v3.3.194) — incremental re-index**: the index persists, per script, the PRISTINE pre-S4b analysis it extracted (`cache/ixevidence_{key}.json.gz`, gzip level 1) plus a per-file identity manifest (`cache/index_manifest.json`); the identity is `md5(EXTRACTOR_VERSION + "\|" + rel_path + sql_text)[:12]`, so an UNCHANGED script is REPLAYED from its evidence snapshot and only changed/new scripts re-extract (S4b + C-5 star expansion always re-run — workspace-wide). `index_change_diff` (=`get_index_freshness`) is the O(files) content diff the catch-up UI reads — PIPELINE-scoped counts, `None` before the first index, DDL churn reported separately in `schema_changed_count`; `is_index_catching_up` is the in-process registry behind the search 409 gate. Measured baseline being removed: `POST /index` 2.28–2.37 s on the 106-pipeline-script `tpcds_qualified` corpus, identical on every open, 70% inside `run_full_analysis`. **Atomic writes**: `_write_json_atomic` → `app.services.atomic_io` for every artifact; `filtered_index.json` is refreshed or cleared on every index (`filtered_index_cleared` in the response); the meta write is a CAS under `_meta_cas_lock` with a retry-on-stale loop |
| `services/cache_keys.py` | 118 | `GRAPH_CACHE_PREFIX = "graph_3_2_25"` (single source of truth; `3_2_19` = v3.3.145 def-line/alias/containment, `3_2_25` = K4 ruling 3 paren-balance diagnostics — an INVALIDATION bump paired with `EXTRACTOR_VERSION 2026-08-28.7`, `format_version` stays 4) |
| `services/graph_service.py` | 470 | Cytoscape JSON builder, NODE_STYLES, EDGE_TYPE_STYLE/CATEGORY_MAP, table_fields/alias_map; `_stmt_idx_of` + context/stmt_idx in node data (C-9); `line_start`/`line_end` in node data (v3.3.140); copies `containment` onto graph edge data (v3.3.145, I5 — the flag must reach the walker/filter). **FSC-2 (shipped v3.3.195)**: the model-cache contract lives here — `MODEL_CACHE_PREFIX`/`MODEL_CACHE_FORMAT_VERSION`, `extract_alias_of`/`write_model_cache`/`load_model_cache` (every guard failure → `{}` → the pre-FSC-2 label-rule fallback, never a poisoned model) and `graph_with_alias_of` (shallow node copies; never mutates the served payload) |
| `services/highlight_strategies.py` | 268 | Display module (v3.3.145): `STRATEGIES` dict + `get_strategy(name)` — default `single_line` (node-carried `line_start`, D2 line-0 filter, adjacent-line merge), `label_only` → `[]`; unknown names fall back; extensible for future strategies (span etc.); R44 — `_anchor_line` anchors a WINDOW edge on the window application's own OVER line |
| `services/logger.py` | 357 | SSE pipeline logger. **MSC-6 (v3.3.194) — the registry is a FAN-OUT, not a ref count**: `_log_queues[ws_id] = {consumer_id: ConsumerQueue}` — one bounded queue per SUBSCRIBER (500, drop-oldest), and every producer line is delivered to ALL of them. It used to be ONE ref-counted queue per WORKSPACE, so two participants (or two tabs) SPLIT the stream — each pushed line was drained by exactly one reader, and a 13-line diagnostic block reached alice as 1 line and bob as 0. `_push` snapshots the consumer set under the lock and never recreates a dropped queue; `ensure_queue` is a deprecated shim; no idle executor thread is parked |
| `services/heavy_gate.py` | 111 | **MSC-1 (v3.3.194, CRITICAL) — the global heavy-op gate is wedge-proof.** `HeavyGate` used to keep per-call state (`self._acquired`) on the MODULE-LEVEL SINGLETON every heavy-op endpoint shares: a refused (409) entrant overwrote the holder's flag before the holder unwound, neither `__exit__` released, and the module global `_busy` stayed True FOREVER — every search, any user, any workspace, answered 409 "system busy — please wait" until the container restarted (reproduced live at 0% CPU after one concurrent burst). The acquisition now lives on a per-call `_GateToken` holding ITS OWN `acquired`/`released`, kept on a per-thread LIFO stack (`threading.local`); `__exit__` releases only what ITS OWN `__enter__` acquired, once. The singleton and the one global `_busy` stay — the serialization is unchanged, only the bookkeeping moved; `__bool__` preserves the routers' `with gate as acquired: if not acquired: 409` shape. Tests `tests/test_heavy_gate.py` (12, incl. the deterministic wedge sequence + an 8-thread hammer) |
| `services/audit_service.py` | 203 | Per-workspace activity trail + server-global audit (NDJSON). **MSC-3 (v3.3.194)**: the full action set the server actually performs is now written — `workspace_created`, `visit_start`, `search`, `l2_opened`, `layout_saved`, `visit_end`, creator `scan`+`index` (close = `visit_end`) — for real sessions only, so the History panel's "who did what" is no longer a single `workspace_created` line no matter what a participant did. BOUNDED: the trail NEVER holds more than `ACTIVITY_CAP = 200` records (the MSC-5 views.json lesson); the cap trim is a read-modify-write, so it is serialized by a per-workspace `.activity.lock` flock held on a DOTFILE (the trim's `os.replace` swaps the inode out from under a lock held on the data file); detail strings clipped to 200 chars. Appends are real `O_APPEND` single-writer writes, never read-modify-write. Tests `tests/test_audit_trail.py` (16) |
| `services/atomic_io.py` | 51 | **Shared atomic-write helper (P1 item 3-i, v3.3.194)** — `atomic_write_text` / `atomic_write_bytes`: unique temp name (`.{name}.{uuid8}.tmp`) + `os.replace`, best-effort temp unlink on `OSError`. Every index/cache/meta write routes through it, so a concurrent reader (a participant loading the index, `l2_builder`'s cache read, `filter_service`) sees either the whole old file or the whole new one, never a torn one. Callers: `folder_index_service` (index/report/manifest/evidence .gz/file_tree), `dataflow_service` (`_atomic_write_text` delegates — schemas, graph cache, views.json), `filter_service` (`filtered_index.json`, off the event loop), `audit_service` (activity records). Residual: `workspace_service._write_meta_cas_locked` still hand-rolls the same temp+replace shape instead of calling this — cosmetic, flagged for the release-gate pass |
| `extractor/variable_extractor_v2.py` | 5168 | Role-based Identifier walking + S1–S6 orphan resolution; **S4a auto-attribution** (`_finalize_schema_candidates`, R6 field==table collision guard), statement-anchored loc (R22-L16: type-aware `_is_as_keyword` — string literals never the anchor; C-13b: token-position anchor), dict-of-dicts script_schemas; C4a unified stats (`resolved`/`unresolved_count`/`coverage_pct`). **v3.3.138**: contexts `TOP{stmt_idx}` (C-9), `_walk_join_key_expressions` (B-series Phase 2), label sanitation (B5). **v3.3.139**: order-independent join-key pairing (`_pair_join_key_sides`). **v3.3.140**: phantom dedup (`_explicitly_walked_selects` prune — subquery-interior columns registered once); statement-scoped line lookup (`_stmt_anchor_lines` + `_record_stmt_anchor` at `_walk_select/_walk_insert/_walk_merge/_walk_create`, `_find_position_scoped` — text-search expr[:40] within `[anchor, next_anchor)`, nested-context anchors excluded; `_add` uses it); PARTITION walk handles `exp.Column` + `exp.EQ`(Column left) on the Table node; `EXTRACTOR_VERSION = "2026-08-07.2"`. **v3.3.145 (I1/I2, definition-line resolution)**: vars carry DEF-site lines from the pre-tokenized stream (`self._tokens`, token `.line/.col`, 1-based) — `_find_position_scoped` text-search DELETED (patch layer); `_stmt_anchor_for(context)`; I2: `_register_column` sets `var.source_tables = [_resolve_alias(table, scope)]` (no early return — qualified columns attributed at extraction time); B3: `_attribute_output_containers` post-pass (CTE body outputs → own CTE, subquery/derived outputs → own VIRTUAL_TABLE); records `parse_errors` on ExtractionResult (case-3); `EXTRACTOR_VERSION = "2026-08-08.1"`. **R44/R45 (2026-08-28, SHIPPED v3.3.195)**: occurrence-side field registration — families 1/2 write-side + derived-read twins, family 3 occurrence-line twins for `_add`-collapsed 2nd..Nth occurrences (`_collapsed_occurrences` + `_register_flow_occurrence_twins`; Fix C: the occurrence-line search is bounded by the group's own paren scope `_paren_scope_bound` and never claims a line a nested scope owns `_scope_line_owner`; Fix D: `_base_var_for` matches the group's FULL casefolded identity; Fix E/F/G: per-clause line pairing `_line_clauses`/`_occurrence_clause`, spelling-insensitive `taken` computed once, a bare identity only matches BARE token occurrences), `_register_groupby_twins` GROUP-BY twins, K3 expression-fragment guard. **K4 ruling 3**: `_paren_balance_errors` — structural paren-balance diagnostics, ONE tokenizer pass over the original script split at `;` tokens. `EXTRACTOR_VERSION = "2026-08-28.13"` (line 310; shipped v3.3.197 — `.9` = the G1 adjudicated batch, `.10` = G7's RC-C closure-continuation fix, `.11` = M-T1's `skip_parens` TVF alias anchors (decision #53), `.12` = V5's R46d continuation twins: arm roles + the family-4 JOIN-ON AND legs `_register_join_leg_twins`, decision #55, `.13` = V8's canonical walker order + the 3a/7-A wave, decision #58. Fix A stage 2 and Fix D part 2 stay WITHHELD) |
| `extractor/dependency_graph.py` | 1492 | VariableDefinition → VariableDependency (16 edge types); Phase 6b JOIN-key expression edges + REF classification (B-series Phase 2). **v3.3.145 (I3/I4)**: Phase 2 ALIAS = one edge per `alias_of` exact source-var id (name-matching cross-product DELETED; `id_index`/`var_order` support); Phase 7/8 anchors via `_pick_anchor` (candidates `_TABLE_TYPES` with `0 < line_start <= v.line_start`, max line, ties: empty `source_tables` > non-VIRTUAL_TABLE > registration order; `_parent_ctx` ancestor walk; global first-match DELETED; no candidate → skip); Phase 4b tags SCHEMA container→nested ⟐VT edges `containment=True` (I5). **R44/R45 (2026-08-28)**: Phase 4d-gb emits the SCHEMA belongs-to edge for GROUP-BY/occurrence twins (the twin's qualifier is its physical owner, so Phase 4d's prefix match misses it and Phase 8's bridge alone leaves it disconnected — topology check "no connection from source table"); `_twin_group_admits` admits a family-3 twin whose group collected a clause its own label lost. **v3.3.195 wave (shipped)**: Phase 4d-gc admits a MERGE/predicate-clause `{owner}.{col}` column on the model's OWN schema evidence — a qualified read resolved to `owner` in the same statement, never owner-spelled (decision #52, blast radius exactly 7 edges corpus-wide); Phase 3's container-PROVENANCE producer pick is a TOTAL ORDER `(line_start, var_order[id])` and guard 3b refuses a producer→reader leg when reader→producer already exists (X1, decision #51); `line_clause_map` feeds J1's JOIN-ON-line test; Phase 9 + the family-4 JOIN-ON AND-leg pass mint R46d's continuation-twin edges (`EXTRACTOR_VERSION .12`) |
| `extractor/sql_line_mapper.py` | 86 | SQL expression → line mapping for `highlights` (D1: comment lines skipped, v3.3.139). **v3.3.140**: prefers var-carried `line_start`/`line_end` (statement-scoped) when > 0; text search kept as stale-cache fallback |
| `extractor/lineage.py` | 2684 | `compute_field_lineage()`, `filter_relevant()` (R18). **R44 (SHIPPED v3.3.195)**: occurrence-coverage admission rounds in `compute_field_flow`, all additive (user ruling "flow-only must cover all occurrences") — R0 case-insensitive entity match, R1 write-completion (a constant projection's output VT is admitted so the write leg renders), R3 derived-product admission (a var carrying the field part whose holder reads the searched table in its own scope is an occurrence), #399 option b′ (the searched table part may name a SQL ALIAS — union the alias's owning entities, gated on no entity hosting the field). **v3.3.138 (B-series Phase 1)**: SUBSET `{propagates_value: False, always_bidir: False}` — never walkable; JOIN rule admits expression nodes unconditionally, others on production evidence; None-guards. **v3.3.140**: `compute_field_flow()`/`filter_by_field_flow()` — strict table.field walker (FIELD_LIKE/FIELD_LAND/NEVER sets; ALIAS iff source_tables[0]==target; FILTER/JOIN iff seed-zone endpoint; DML forward-only; owner resolution + container rule; identity admissions to fixpoint) — legacy functions byte-identical. **v3.3.145 (I5)**: containment edges excluded — `_is_containment(ed)` helper (dict-key + object-attr forms), skipped in `compute_field_flow` adjacency + `filter_by_field_flow` output. **v3.3.195 wave (shipped)**: the R46c `_value_cone_gate` runs after the closure fixpoint (downstream only) and shrinks the served closure to the searched field's VALUE CONE — `CONE_EDGES` only (REF/COMPUTED/TRANSFORM/AGGREGATE/WINDOW/ALIAS/SET_OP/SUBQUERY/DML; never SCHEMA/FILTER/JOIN/INDIRECT/CORRELATED/SUBSET/ROW_FLOW as cone carriers), the searched table's own compound stays whole (`_OWN_BOX_CHIPS`), `_VALUE_CONE_GATE=False` restores the pre-R46c closure EXACTLY (the before/after pins flip the switch itself); V7's two R-GATE switches `_PHANTOM_COPY_GATE`/`_DERIVED_CONTAINER_CHIPS` fix the two opposite-direction admissions (decision #54) |
| `extractor/schema_inference.py` | 180 | `infer_table_schemas()` — 7-pass iterative stabilization |
| `extractor/physical_model.py` | 755 | The PHYSICAL layer (J12-10 stage 1), between syntax and display: ONE `PhysicalTable` per table NAME (qualified name is the key), per-occurrence role SETS (`read`/`write`/`merge_target`/`cte_fed`/`partition`), `alias_by_var_id` (the extraction alias truth the strict walker consumes), `PhysicalEdge`s derived ONCE from the dependency graph with the 16 types unchanged. Every original var id survives as an occurrence id — nothing dropped, no reconstruction machinery. **V6/FSC-2** persists it beside the graph cache (decision #50); **H12** made the build cheap (decision #56) |
| `models/variable.py` | 127 | VariableType enum (16 types), VariableDefinition, VariableDependency; `VariableDefinition.alias_of` (I4: exact source var id for ALIAS edge) + `VariableDependency.containment` (I5) |
| `models/sql_model.py` | 161 | Canonical taxonomy: node↔edge types mapped to SQL |
| `main.py` | 295 | FastAPI app init + router mount; `_VersionedStatic` static mount (v3.3.190 cache headers — index.html/no-asset paths `no-cache`, content-hashed `assets/*` `immutable`) |

### Frontend (`frontend/src/`)

| File | Lines | Role |
|------|-------|------|
| `DataFlowApp.jsx` | 1921 | Data Flow Debugger main component (search, view persistence, resolution report, `schema_evidence` state; R22: `applyL2Result` + L2 not-in-flow banner, L1 no-matches message banner; R23: no browser auto-restore — clean start on load, one-time `df_last_search_view` purge). **v3.3.191+**: #400 — the no-flow banner carries an "Open <script> full graph" button (a no-flow search matches scripts but its L1 is empty, so there was no UI path to them); a not-in-flow strip lists the scripts outside the flow, each clickable into its full L2; F-B2 `sqlLineNotice` — a line-0/absent `line_start` shows "this element has no SQL line" instead of silently clearing the previous highlight. **P1/P2 fast open (v3.3.194)**: an existing workspace opens from `getWorkspaceTree` + `getWorkspaceIndex` (persisted reads); the client fires `POST /index` ONLY when the payload's `freshness` content diff is non-empty AND the user is the creator — a zero-diff open issues no rebuild call at all. While a catch-up runs: the `catchup-panel` bar ("Catching up: N changed script(s)… search reopens when the index is whole."), the search panel WITHHELD, and the 409 replay path recognises the catch-up by its OWN sentence (distinct from the heavy-gate 409) and replays the withheld search when the run ends; a participant gets an informational hint and never triggers the rebuild. `isCreator` gates `canManageViews` (the per-view "×") and the workspace button label |
| `App.jsx` | 857 | SQL Analysis (legacy single-script) |
| `components/DataFlowGraph.jsx` | 473 | Cytoscape renderer (no edge-hover tooltip — removed #240) |
| `components/SqlPanel.jsx` | 399 | SQL display + syntax highlighting |
| `components/FilterPanel.jsx` | 426 | Filter upload UI + warning banner (R2), renders `ignored_rows`; F5 (audit #383): canonical-key echo + inline "no such table.field in the index" message replacing the silent no-op; F-B2 — an autocomplete dropdown renders only while the typed name does NOT yet resolve AND its option list is non-empty (a resolved name leaves no overlay to cover or click-block the next input; typing never spawns an empty dropdown) |
| `components/ResolutionReport.jsx` | 99 | Orphan resolution coverage badge + breakdown (R20) |
| `components/WorkspacePanel.jsx` | 133 | Workspace upload/scan/index UI. **v3.3.194**: the workspace action is LABELLED BY ROLE — creator "Delete Workspace", participant "Remove from my list" (the same endpoint does a different thing per role); "Indexed 5m ago" staleness line (`formatIndexedAge`, passive display over the payload's own timestamp, unparseable → not rendered); and there is **NO manual re-index control for anyone** (user ruling 2026-08-31) — the automatic content-hash catch-up is the only re-index UI, and corrupt/missing caches fall back to a full build on open |
| `components/FieldStoryBar.jsx` | 195 | Field Story step-through bar (v3.3.188, R40.3): numbered step chips, ◀/▶, autoplay 3s, ✕ dismiss — presentational, ALL state in DataFlowApp; relocated below the SQL panel (v3.3.189). **R40.13 (v3.3.194)**: gains the string-match cluster — the show/hide toggle, the `N string matches · M in flow · K not in flow` counter, the `◀ 3/17 ▶` browse readout (wraparound, `–/17` while inactive) and the disabled-while-hidden rule; `flex-wrap: wrap` so the cluster drops to its own row in the default 420px L2 panel and the counter is never ellipsised |
| `utils/layoutCore.js` | 244 | Shared layout: `fieldPositionsForTable()`, `positionTableFields()`, `applyLayout()` |
| `utils/snakeLayout.js` | 107 | Snake/wrapping layout |
| `utils/elkLayout.js` | 239 | ELK layered layout |
| `utils/resolutionReport.js` | 93 | Stats normalization (prefers unified `unresolved_count`/`coverage_pct`) |
| `utils/flowVisibility.js` | 504 | L2 two-view toggle helper: resolves initial flow-only state and applies `.show()/.hide()` visibility from `flow_node_ids`/`flow_edge_ids` (never re-layout — positions preserved across toggles). merged-view filter chrome: table-border loop-line (`capA_/capB_/capL_<edgeId>`, zoom-compensated) + `centerOnSeed` post-toggle re-center — **the synthetic `⟂` caption NODE is RETIRED v3.3.194** (user ruling 2026-08-31: it was painted a SECOND time by the `FILTER_SELFLOOP_STYLES` edge-label rule, and because the enlarged loop's midpoint sits OUTSIDE the table box neither copy was hidden by a node fill — `east5_stzfxxb.p_dt` showed two identical `⟂ p_dt (filtered @L190)` texts on one loop; `FILTER_CAPTION_STYLES` is now an empty export still spread by `useCytoscapeGraph`). v3.3.191+: data-driven `loopstep` per self-edge (`halfWidth + 150`) for `control-point-step-size` (R40.8 — the real self-loop geometry knob); R41 `recenter:false` on user-initiated Fit. **Border-scoring assignment (labelled v3.3.195 in the code comment)**: `borderScore()` counts, per side, the neighbour boxes overlapping the arc band plus the ordinary edges attaching there, and `assignLoopSides` anchors the LABELLED loop on the freer border, sharing it only when the opposite one is occupied; 3+ loops keep the alternation as the greedy fallback; placement is deterministic (highlight_line, then id). **V2-N1 (2026-08-29)**: the searched `is_target` seed chips are EXEMPT from the merged-view zero-edge chip hiding |
| `utils/stringMatch.js` | 167 | **R40.13 — the NAIVE string-match diff layer (v3.3.194, pure functions, no React, no parsing, no network).** `computeStringMatches(sqlText, fieldName)` → 1-based ascending lines (a line with 3 occurrences is ONE entry; comment/string-literal lines INCLUDED by design — it is the "what would a dumb grep see" baseline, so matching the chip's own birth line is correct); `classifyMatches(matches, flowLines)` → two DISJOINT ascending arrays/Sets `covered`/`missed` (an empty baseline classifies everything as missed — the truthful "the engine claims nothing here"); `flowLineSet(l2Result)` → the coverage baseline = `highlight_line` of `flow_edge_ids` ∪ `line_start` of `flow_node_ids`, integer ≥ 1, read from the DETAILED `graph` namespace (never the merged projection) — which is what makes the coloring identical across the flow-only/full/merged toggle; `buildBoundaryRegex` = case-insensitive lookarounds over `[A-Za-z0-9_$]`, NEVER `\b` (`$` is an identifier character in Hive/ODPS but a regex non-word char, so `\b` accepts `p_dt$x`/`x$p_dt`; flags are `"i"` ONLY — a `"g"` flag makes `.test()` stateful and silently skips lines). NOT a correctness claim: a red line is a difference to inspect, not a bug |
| `utils/fieldStory.js` | 686 | Field Story derivation (v3.3.188, R40.3): the searched field's closure as ordered steps birth→written→read→**reappears**→joined→filtered→consumed (R40.12: Reappears = own-table SCHEMA occurrence-twin edge at a foreign line — strict admission, user-ruled 2026-08-30; Joined/Transformed added R40.10 — 7 stages, budget ≤10). **R40.12-A / G6 (2026-08-31 per-field rule audit): a step is told only when the payload carries FIELD-level provenance — an endpoint that IS one of the searched field's OWN chips (seed + every occurrence twin); a chip-sourced value leg resolving to the own table = birth at the production line, to another table = consumed at the DML anchor; the ⟐ routing family is matched by type AND the `⟐` name marker (the old `output_table` type test was dead code); where the payload is silent about the field the story is silent too — the step is DROPPED, never re-anchored** (see #37 for the 28% → 95.8% audit) — PURE projection of the served payload; each step carries BOTH edge-id namespaces (detailed `l2e_*` + merged `l2m_*` via `mergedEdgeIds`) |
| `utils/nameFilter.js` | 90 | Autocomplete name-filter mirror: typo-tolerant matcher (Levenshtein-≤1 fallback) mirroring backend `folder_index_service.autocomplete()`; F5 (audit #383): `resolveNameCi()` case-insensitive resolution to the canonical index key |
| `hooks/useCytoscapeGraph.js` | 512 | Cytoscape lifecycle: init, drag (recomputes from frozen offsets), layout dispatch, L2 flow-only ↔ full toggle via `applyFlowVisibility` (pure .show()/.hide() — never re-layout). R41 (v3.3.191+): `minZoom` 0.08 + Fit passes `recenter:false`; `CY_CORE_OPTIONS` exported (frozen shared core options: `wheelSensitivity` 0.3, `minZoom` 0.08, `maxZoom` 5) |
| `config/layout.js` | 80 | Layout constants (single source of truth) |
| `api/client.js` | 313 | API client + `errorDetail()` (L12; R23: `getWorkspaceInfo`/`scanWorkspace` wrappers removed). **K4 ruling 4**: `searchDataFlow` defaults `direction='downstream'`, so an omitted argument cannot re-introduce the upstream contract the API no longer honors. **v3.3.194**: `getWorkspaceTree` (returns `null` on any non-OK — a missing tree is a state, not an error) + `getWorkspaceIndex` (throws with `err.status` attached, which is what lets the catch-up 409 be recognised by status AND sentence) + `deleteViewChild(wsId, parentViewId, childId)` → `DELETE /workspace/{id}/views/{childId}`, the route that actually exists — the previous `…/children/{childId}` URL was never implemented and 404'd for every role |

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
30. **Merged self-loop filter labels + flow-line invariants (v3.3.181, R39;
    captions RETIRED v3.3.194, user ruling 2026-08-31)**: R32 promotion turns
    absorbed FILTER edges into self-loops. The `⟂ <fields> (filtered
    @L<line>)` caption is GONE — it was painted twice (the
    `FILTER_SELFLOOP_STYLES` edge label AND the v3.3.190 caption node, both at
    the loop midpoint, which sits outside the table box so no node fill hid
    either). The curve stays (`FILTER_LOOP_GEOM_STYLES`, per-edge `loopstep`,
    `loopdir`): parallel loops on one table alternate sides and the LABELLED
    loop takes the FREER border — `flowVisibility.borderScore` counts, per
    side, the neighbour boxes overlapping the arc band (nodes paint above
    edges; a loop pushed behind the alias box `a@141` lost ~7x of its pixels)
    then the ordinary edges attaching there; ties go LEFT. The absorbed line
    number travels through the R37 click→SQL
    channel and the Field Story "Filtered" step. `FILTER_SELFLOOP_STYLES` /
    `FILTER_CAPTION_STYLES` are now empty exports (still spread by
    useCytoscapeGraph). Two standing gates in `test_flow_line_invariants.py`:
    INV-1 every DML field-line has ≥1 closure edge (DDL ADD PARTITION lines
    are the documented exception — new coverage there fails the test); INV-2
    every closure edge carries a SQL line.
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
    silent no-op (never guesses — K4.4; the TVF-alias L0 case that used to
    hit it is CLOSED by M-T1 / R52: the alias anchors on its own call line
    via the run matcher's opt-in `skip_parens`), first line only, L2
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
37. **Field Story Joined/Transformed (R40.10, 2026-08-28) + Reappears 7th
    stage (R40.12, audit 2026-08-30)**: edges of type
    JOIN/TRANSFORM/COMPUTED/WINDOW/AGGREGATE touching the seed/table are
    told as their own step (label "Joined/Transformed"), and a SCHEMA edge
    from the searched table's OWN compound INTO the seed chip is told as
    "Reappears" — the field occurs again here, on a line its chip doesn't
    show (a group/join/partition/predicate occurrence). Order:
    `KIND_RANK` birth/written/read/**reappears**/joined/filtered/consumed —
    7 stages, the occurrence evidence preceding the joined/filtered steps it
    explains. Reappears admission is STRICT, all four conditions: `SCHEMA` +
    `source` = the searched table's compound + `target` = the seed chip +
    valid `highlight_line` ≠ the chip's own `line_start`. The ⟐output/
    alias/CTE twins of the same field emit their own SCHEMA edges INTO that
    chip and stay out (they are other boxes' copies, and one line would be
    re-told as many steps); the chip's own line stays out (birth/read
    already tell it). The label names NO clause — 4 of the audit's 9
    admitted lines are not GROUP BY. Evidence (AD-quality, payloads built
    in-process via the service layer over the 4 samples): the 9 examples
    each gain exactly one reappears step — bdm_fin_lrr_key_base_info.product
    PL@246, lending_ref SUP_M@59, BDM_ACC_WRITEOFF.busi_no RFN@277,
    bdm_acc_loan_info.repay_acct_no RFN@1413, ODS_HUB_SSINRTP.X5GMAB RFN@489,
    ODS_CUPD_CLD_ACCTMASTER_NEW.acnw DL@64, lrr_key PL@247, product DL@529,
    acnw PL@21; the ruled strict trade-off is dm_flag2 RFN keeping exactly
    written-768 / written-1168 / consumed×2 (its L1119 mask line reaches the
    chip from an ⟐output compound, not from its own table). R40.10's
    evidence: random-10 field audit — 49 previously-unclassified narrative
    edges left source-side fields at 1–2 steps; +30 projected steps across
    7/10 fields.

    **AMENDMENT (2026-08-31, R40.12-A — the per-field rule audit):** a
    per-field audit of the classification (117 searchable
    `(table, field)` pairs of EAST5_STZFXXB_M.sql, 597 told steps, ground
    truth = the script text + a hand-verified token/alias model built
    independently of the module) scored **167/597 = 28%** steps true of the
    field — birth 3/49, read 0/95, consumed 32/267, joined 51/105 (written,
    reappears, filtered were 100%). Four rules were re-ruled in
    `utils/fieldStory.js` (frontend-only; the mechanical frame — seed
    selection, INV-2, `(kind,line)` grouping, `KIND_RANK` — is untouched):
    **Fix H**: `consumed` had no field-leg requirement AND its ⟐output
    exclusion tested `type === 'output_table'`, a type that does not exist
    in served payloads (routing intermediates are `intermediate_table`; the
    guard was dead code) — every write leg in every closure landed in
    `consumed`, including each field's own AS-alias birth line. Now: the
    routing family is matched by type **and** by the `⟐` name marker; a
    value leg is the field's only when one of the field's OWN chips SOURCES
    it; the leg is resolved through the routing intermediate's single
    outgoing write leg (no single leg → untold, never guessed) — resolving
    to the field's own table = **birth** at the leg's own line (the
    SELECT-list AS-alias/PARTITION line where the value is produced, e.g.
    `… AS cjrq` @74), to another table = **consumed** at the consuming DML
    statement's line (the routing intermediate's `line_start`, not the
    production line — that line is the birth), with the routing leg riding
    the step's evidence so the reader sees who consumes it. **Fix M
    (table-path)**: an edge is a step only when a chip of the searched
    field is an endpoint — every chip of the field on the searched compound
    (the seed + the R44 occurrence twins), not the seed alone; touching the
    compound alone is the table's path (191 TABLE-PATH + 52 PHANTOM steps).
    A read additionally requires the chip to SOURCE the leg
    (`compound → chip` value copies measured 8/8 wrong) and the line to be
    the endpoint chip's own `line_start`; a joined/filtered step requires a
    line that is neither the compound's anchor nor (for JOINISH types) the
    chip's own line (a JOINISH edge there is that line's own expression →
    told as `read`; a FILTER there IS the field's predicate → stays
    `filtered`). **Fix M (birth)**: birth no longer requires
    `highlight_line === the table's line_start` — that is the FROM/JOIN
    anchor for a source table (46 fake `Birth @LEFT JOIN …`) and never the
    AS-alias line where a target column is produced; a source-side field has
    NO birth stage (its honest stage is `read` at its first occurrence), and
    a birth line absorbs the other chip edges on that same line (the
    PARTITION binding beside the value leg). Re-run of the SAME audit over
    the SAME 117 payloads: **207/216 = 95.8%** true of the field (birth
    61/61, read 34/34, written 63/63, reappears 14/14, filtered 4/4, joined
    10/13, consumed 21/27), **0 H defects** (was 138), 597 → 216 steps, and
    116/117 stories non-empty (the one empty story is a chip the walker
    attributed to the wrong table — nothing in its closure is true of the
    field, so nothing is told). Scored by the audit's own published engine
    unchanged the figure is 69%: the delta is only that engine's birth
    branch, which had no OK case for a target column's AS-alias line (its
    own `correct` field said `birth @L74` for the step it judged
    WRONG-STAGE); the amendment's ruling (Fix 1c) is that the AS-alias line
    IS the birth. The 9 residual M defects are NOT client-fixable — they
    need payload fields that do not exist: 6× `consumed` on a SELECT-output
    alias the index attributed to a SOURCE table (`bz`←`a.ccy_code`,
    `dkje`←`b.loan_amt`, … — the walker builds a value leg for the alias
    chip), and 3× `joined` where a COMPUTED edge is addressed to the wrong
    output chip (`CASE … ` @51 → the `stzfdxhh` chip, @71 → `RESERVED_8`/
    `RESERVED_10`). Both are backend follow-ups (either stop attributing
    output aliases to source tables / fix the expression→output addressing,
    or expose the per-edge field hop that today lives only inside the
    display `reason` string as structured edge data). Flagship regressions
    hold: the 9 R40.12 examples keep exactly their audited reappears steps,
    and dm_flag2 RFN keeps written-768/written-1168 (its two ⟐-routed
    "consume" legs drop — they carry no dm_flag2 chip, the audited Fix-H
    shape). Tests: `fieldStory.test.js` rewritten for the corrected
    canonical closure (3 steps for `east5_stzfxxb.p_dt`: birth-41,
    written-41, filtered-190) + extended with one suite per rule (398
    frontend tests green, was 384).
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
43. **R44 walker occurrence coverage — SHIPPED v3.3.195 (user
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
    snapshot regeneration RAN at the v3.3.195 release gate — 108
    committed baselines, all green (commit `3777e9e`; R44.3 ✅). Row-level
    record: `wiki/REQUIREMENTS_TRACEABILITY.md` §"R44".

44. **Identifier folding is two conventions, provably equivalent here
    (AD2-E, 2026-08-29)**: the extraction/graph side
    (`variable_extractor_v2`, `dependency_graph`, `l1_builder`,
    `l2_builder`) folds with `.casefold()`; the index/lineage side
    (`lineage`, `folder_index_service`, `filter_service`) folds with
    `.lower()`. The two agree on every identifier this corpus can
    produce — measured: **0 divergent identifiers across the 338-file
    sample corpus** (a divergence needs a non-`iff`-foldable character
    pair, i.e. ß/ς/ﬁ-class). Do NOT "fix" either side per-site: if a
    corpus ever contains such a pair, the authority is the DB
    collation and the fix is ONE shared `fold_ident()` helper that both
    sides call — never a sprinkling of local `.lower()`/`.casefold()`
    rewrites, which is how the two conventions drift apart again.

45. **String-match diff layer is naive by design, color-coded by flow
    coverage, browsed on its own cursor channel (R40.13, ruled
    2026-08-31, ships v3.3.194 — frontend-only)**: after a search the SQL
    panel also renders a NAIVE case-insensitive match of the searched
    field name over the WHOLE script — comment lines and string literals
    INCLUDED (it is the "what would a dumb grep see" baseline, so
    matching the chip's own birth line is correct, not a defect) — and
    every matched line is banded by whether the ENGINE's flow closure
    covers it (green = covered, red = not), with the counter
    `N string matches · M in flow · K not in flow` in the Field Story
    bar. Boundary rule is a lookaround over `[A-Za-z0-9_$]` —
    `(?<![A-Za-z0-9_$])NAME(?![A-Za-z0-9_$])`, escaped name, case-
    insensitive — NEVER `\b`: `$` is an identifier character in
    Hive/ODPS but a regex non-word char, so `\b` accepts `p_dt$x` and
    `x$p_dt` (the two conventions agree on trailing digits, so
    `p_dt2`/`p_dt_backup` are safe under both). The coverage baseline is
    ALWAYS the flow closure's highlight set — `highlight_line` of
    `flow_edge_ids` ∪ `line_start` of `flow_node_ids`, read from the
    DETAILED `l2Result.graph` namespace (never the merged `l2m_*`
    projection), integer ≥ 1, empty when the flow sets are empty — which
    is what makes the coloring identical across the flow-only/full/merged
    toggle. Browsing (`◀ 3/17 ▶` in the Field Story bar, wraparound,
    ascending) uses a SEPARATE cursor prop + state that scrolls the panel
    and outlines the active line; it never writes the R37
    `sqlHighlightLine` channel, and the engine's amber left border stays
    untouched and legible under the layer's right-border band (three
    tokens, three meanings: amber = engine anchor, green = naive∩engine,
    red = naive-only). Pure display over the already-served payload: no
    backend, no API, no cache key, no snapshot, and NOT a correctness
    claim — a red line is a difference to inspect, not a bug
    (`utils/stringMatch.js` + `SqlPanel.jsx` + `FieldStoryBar.jsx` +
    `DataFlowApp.jsx`; design of record: `wiki/REQUIREMENTS_TRACEABILITY.md`
    §"R40.13"; requirement + acceptance criteria:
    `requirements_v2.md` §"Amendment (2026-08-31)").
    **IMPLEMENTED v3.3.193 working tree (R40.13, frontend-only, 42 new
    tests).** Three implementation notes where the sketch's literal wording
    needed a correction the design intent survives: (1) the DOM carries the
    tokens `string-match covered` / `string-match missed` (as the sketch's own
    class-list text says), so the CSS selectors are the compound
    `.sql-line.string-match.covered` / `.…missed` forms — the sketch's
    `.sql-line.string-match-covered` selector literal would match nothing;
    (2) the searched field is resolved through the PARENT search row
    (`storyTarget.field`) rather than the sketch's `activeView?.field` — an
    active L2 view is the CHILD row, which carries no `field`, so the literal
    read would have hidden the layer on every L2; (3) the Field Story bar is
    `flex-wrap: wrap` so the string-match cluster drops to its own row in the
    default 420px L2 panel — the counter is the feature's whole point and is
    never ellipsised (`flex-shrink: 0`); at panel widths that fit the row the
    bar renders exactly as the single-row sketch. `classifyMatches` returns
    Sets (ascending iteration order) to feed the `Set<int>` SqlPanel props
    directly.

46. **Opening a workspace is a read; only a content change re-extracts
    (v3.3.194, P1/P2)**: the baseline this replaces is that every open re-ran
    the whole extraction pipeline — `POST /index` measured 2.28–2.37 s on the
    106-pipeline-script `tpcds_qualified` corpus, IDENTICAL on the 2nd and 3rd
    open, 70% of it inside `run_full_analysis`, because the per-script analysis
    caches were rewritten every run and never read back. Now both the creator
    and a participant open from persisted state
    (`GET /workspace/{id}/tree` + `/index`), and re-index is INCREMENTAL: each
    index persists the pristine pre-S4b analysis per script
    (`cache/ixevidence_{key}.json.gz`) plus a per-file identity manifest
    (`cache/index_manifest.json`) keyed by
    `md5(EXTRACTOR_VERSION + "|" + rel_path + sql_text)[:12]`, so unchanged
    scripts are REPLAYED and only changed/new ones re-extract — S4b and the C-5
    star expansion always re-run (workspace-wide). A zero-diff open issues NO
    `POST /index` at all. Change detection is by CONTENT, never mtime (a test
    pins that touching a file without changing it does not fool the reuse). A
    stale creator open self-heals: one automatic re-index, a
    "Catching up: N changed script(s)…" bar, search withheld, index-derived
    searches answered with an explicit retry-able 409 for that window (the
    previous index would have lied — a field present only in a just-added
    script would come back as "not queried by any script"), the withheld search
    replayed when the run ends; a participant gets a hint and never triggers the
    rebuild. There is NO manual re-index control for anyone (user ruling) — the
    catch-up IS the re-index UI. Every index/cache/meta write is atomic
    (`services/atomic_io.py`, unique temp + `os.replace`) and the meta write is
    a CAS under `_meta_cas_lock`, so a concurrent reader never sees a torn
    artifact — proven by a test that re-runs the same harness with the atomic
    write REMOVED and watches the tear come back.

47. **The multi-user contract is enforced, not just documented (v3.3.194,
    M1/M2/MSC audits)**: one writer (the creator) per workspace, any number of
    read-only readers — and the surfaces now say so. The workspace button is
    labelled by role (creator "Delete Workspace", participant "Remove from my
    list"); the per-view "×" is creator-only; `DELETE …/views/{childId}` is the
    only child-delete route (the previous `…/children/{childId}` URL was never
    implemented and 404'd for every role). The heavy-op gate holds its
    acquisition on a PER-CALL token, not on the singleton — MSC-1 (CRITICAL):
    per-call state on a module-level singleton meant one 409-refused entrant
    destroyed the holder's release and every search service-wide answered 409
    until restart. The SSE log stream BROADCASTS (one bounded queue per
    subscriber, MSC-6) instead of splitting one ref-counted queue between
    readers. The activity trail records what the server actually does
    (`visit_start`/`search`/`l2_opened`/`layout_saved`/`visit_end`, bounded at
    200, MSC-3) instead of holding one `workspace_created` line forever. Two
    things stay OPEN on purpose: whether views should be workspace-shared or
    per-user is a product question for the user, not a defect; and the R40.13
    boundary class covers `[A-Za-z0-9_$]` only, so `#` is a boundary character —
    measured zero effect on the current corpus, and changing it needs a ruling.
    Audit record: `wiki/CODE_REVIEW_2026-08-29.md` §6–§9.


48. **Field-involvement admission — "only edges where the searched field is
    involved in the data flow are shown" (USER RULING 2026-08-31, fix team
    J1 — ✅ LANDED, `tests/test_field_involvement_rule.py` 12 green)**: the
    served field closure's EDGES are admitted through
    `l2_builder._apply_field_involvement` (runs after the payload phase, before
    roles/response, and only when a search filter is active — the full view has
    no searched field). The walker's NODE closure is untouched, so R44
    occurrence coverage can never regress; the rule only removes. Two classes,
    both read from extraction-time facts already carried per edge:
    **Class 1 — JOIN OWN-SITE**: a JOIN carrier is served only when its anchor
    line IS a JOIN-ON line (`line_clause_map` in `dependency_graph.py` — the
    extractor's own `_line_clauses` machinery: same tokenizer, same
    `_LINE_CLAUSE_TOKENS`). A collapsed carrier's `defined_in` names the
    GROUP's clause while the line it carries was handed out in stream order
    (R45 Fix B / F-E1), so a projection/read line can inherit the group's
    join-key edge — the ledgered PROJECTION-TWIN-INHERITS-JOIN class (SUP_M
    lending_ref JOIN carriers anchored at the L82 `CASE WHEN NVL(p6.lending_ref…`
    read and the L163 `,p1.lending_ref` write projection; the LFS123 doctrine
    "a carrier whose line is not the relationship's own site does not earn the
    anchor"). **Class 2 — SIBLING-FIELD VALUE LEGS**: a value leg of a
    NON-searched field is that sibling's own flow, not the searched field's —
    its DML write value leg (`_value_edge`), its ⟐output-frame membership
    (SCHEMA op `OUTPUT`), its write-projection read leg (REF op `READ` whose
    source occurrence is stamped `SELECT expr`), and the chain leg into the
    output frame its write drives (a value-carrying edge targeting the ⟐output
    frame whose upstream `_path_hops` carrier is a sibling field occurrence).
    Belongs-to/structural facts of a sibling chip (SCHEMA `TABLE_COLUMN`, ALIAS,
    the table/VT skeleton) stay — the accepted FSB/G9 classes. Display-layer
    mini version of AD3's value-cone gate (v3.3.195 does the full walker
    version). Cross-check (SUP_M × lending_ref): the 6 ledgered over-included
    edges are gone, node set and occurrence coverage byte-identical (14-case
    before/after spot check), Field Story loses exactly the wrong step
    (lending_ref SUP_M `joined@67`). RULE-VS-CANONICAL CONFLICTS (the rule is
    the authority; the user rules on the ground truth): `LFS41`/`LFS123` (JOIN
    carriers anchored at L67, a projection line — the canonical's own LFS123
    note concedes "no join happens there") and `LFD2` (the upstream FROM-source
    JOIN@101, already CR10-"pending"). Those 3 rows put
    `lending_ref↓SUP_M` at E 0.9858/1.0000 and `lending_ref↑DL` at 0.9000/1.0000;
    the other 18 benchmark cases stay 1.0000/1.0000. Tests:
    `tests/test_field_involvement_rule.py`. **RESOLVED 2026-09-01 (R46c
    canonical re-derivation, decision #55): all three rows are REMOVED
    from the canonical with the ruling citation (class X5) and both
    cases are GREEN again — the gate is 20/20 at 1.0000/1.0000 recall
    AND precision, and the two ruled-red benchmark deselects were
    retired from `release.sh` (commit `0ac1c81`).**
    **CORRECTED 2026-09-01 (rule 3a REVERSED by USER RULING, see #58)**:
    the sentence above — *"Belongs-to/structural facts of a sibling chip
    (SCHEMA `TABLE_COLUMN`, ALIAS, the table/VT skeleton) stay — the
    accepted FSB/G9 classes"* — is REVERSED. A sibling's belongs-to edge
    is NOT the searched field's flow, and on write-heavy statements it
    drags every co-written column's chip into the closure as clutter, so
    sibling belongs-to edges are **DROPPED** and the sibling chips the
    drop leaves edge-less are **PRUNED** (`_apply_field_involvement`
    Class 3 + `_prune_orphan_sibling_chips`, flow-only views only — a
    full view stays byte-untouched, it has no searched field). The
    user's ruling is quoted in `wiki/FLOW_ONLY_VIEW_RULES.md` §3a. The
    VALUE-leg half of Class 2 as described above is unchanged — only the
    belongs-to/structural half changed sides.

49. **User management is FILE-driven — `users.allowlist.json` is the whole
    allowlist (R31.35, user-approved 2026-08-31, HIGHEST PRIORITY; ✅ LANDED
    2026-09-01 — `target_deploy.sh` `build_users_env` + `strip_allowlist_comments`,
    the post-deploy log line naming the provisioned EMAILS, `.gitignore` +
    `users.allowlist.json.example`, and `tests/deploy/test_allowlist_logic.sh`
    36 green)**: every service user is configured BY HAND
    in ONE file at the repo root, next to `target_deploy.sh`. **Format
    (frozen)**: a single JSON object mapping email → password —
    `{"admin@hsbc.com":"123456","alice@hsbc.com":"alice-pw2"}` — with `//`
    line comments allowed (the script strips them before parsing, because
    `config.py` parses the value with `json.loads`, which rejects comments).
    **Activation flow**: `target_deploy.sh` reads the file → strips `//`
    comments → auto-merges `admin@hsbc.com` / `123456` when the file omits it
    (M1-D5 closed: the parsed object REPLACES `config.py`'s default, so a
    file without admin used to disable the admin account) → hands the merged
    JSON to the container as `PROVISIONED_USERS_JSON` → the `main.py` lifespan
    force-syncs every entry at startup (`provision_user(force=True)`); there
    is no HTTP provisioning endpoint. **Semantics** (pre-existing R31 rules,
    now file-driven): a new email creates the account, an existing email
    re-syncs its password and revokes its live sessions (M-Po7) — the user
    just logs in again; workspaces/views/indexes are untouched (durable
    `gps_workspace_data` volume); a password under `MIN_PASSWORD_LEN` (6)
    SKIPS that account with a startup WARNING that names the account and
    never the password (M1-D4); an empty/invalid file is a WARNING, not an
    abort — the deploy continues with the image default (`admin@hsbc.com` /
    `123456`) and says so. **Security posture**: the LIVE file is gitignored
    (real passwords never pushed; the `.gitignore` entry and the committed
    `users.allowlist.json.example` are the script team's), and the deploy log
    lists the provisioned EMAILS, never the passwords. **Operator duty**: the
    account store keys on the exact spelling, so case-insensitive email
    uniqueness is the operator's job — `Admin@hsbc.com` and `admin@hsbc.com`
    in one file are two accounts with split workspace ownership. **Non-goals**:
    no in-app user-management API (the admin-API request is ledgered
    separately, task #417), no roles beyond creator/participant, no password
    change flow (an edit + a deploy IS the change), no account deactivation
    (dropping an entry only stops the force-sync — the persisted record
    survives and still logs in with its last synced password). Requirement +
    frozen format + acceptance criteria:
    `requirements_v2.md` §"Amendment (2026-08-31)"; traceability R31.35.

50. **The physical model is persisted beside the graph cache — the served L2
    closure is a pure function of the SQL text (FSC-2, v3.3.195 wave, team V6;
    traceability R49)**: the walker's model was built from the analysis dict
    when an analysis cache was present (the `alias_of` extraction truth) but
    from the cached GRAPH JSON when it was not, and the graph cache does not
    serialize `alias_of` — so the second form fell back to
    `physical_model`'s label-keyed alias rule. Same SQL, two models (RFN:
    28 of 74 `alias_by_var_id` pairs differ; SUP_M 4 of 14), decided by WHICH
    cache survived. Fix = PERSISTENCE, not a smarter fallback: every build
    writes `cache/model_{cache_key}.json` from the SAME analysis the graph was
    built from, and a graph-cache hit that cannot rebuild the model from an
    analysis cache re-derives it from that artifact. Every guard failure
    returns `{}` → the pre-FSC-2 label-rule fallback, so a stale artifact can
    only be IGNORED, never poison a model; old caches without a sibling keep
    working (no hard break) and `purge_workspace_caches` deliberately keeps the
    artifact (it cannot serve stale data — purging it would reintroduce the
    hole). User-visible consequence: an alias-qualified seed (`a.cust_no`) got
    no seed at all under the lossy variant → `search_matched: false` and the
    WHOLE graph (RFN 1053 nodes/6764 edges) instead of its 78-node/221-edge
    closure. Tests `backend/tests/test_model_persistence.py` (12).

51. **The container-PROVENANCE bridge is deterministic, one-way and KEPT
    (X1, v3.3.195 wave; traceability R51)**: Phase 3's bridge wires a container
    body (CTE/SUBQUERY/⟐VT) that produces a value to the outside reader that
    consumes it — the seam where every container chain was value-disconnected
    (RC-C). Three properties are now part of the contract: (a) the producer
    pick is a TOTAL ORDER `(line_start, var_order[id])` — the candidate
    containers live in a set, so the old `producers[-1]` was hash-random across
    processes (7 distinct pick-sets on RFN over 8 PYTHONHASHSEEDs); (b) guard
    3b refuses a producer → reader leg when the reader → producer leg already
    exists (14 direct 2-cycles corpus-wide, was); (c) the phase STAYS — the
    earlier strip-measurement predated the J12-10 walker that consumes
    PROVENANCE edges, and stripping today loses 47–80 lit lines per search.
    Direction is value direction (producer → reader): `lineage` admits the
    forward half unconditionally and gates only the reverse half on the
    searched field, which is what keeps the bridge from fanning a container's
    column out to every same-named var (a plain REFERENCE edge there grew RFN
    `reserved_field9`'s closure 16 → 267).

52. **Belongs-to edges are admitted only on the model's own schema evidence
    (H11 Phase 4d-gc; traceability R50)**: a MERGE/predicate-clause column
    registered under the owner-qualified spelling `{owner}.{col}` used to carry
    no incoming SCHEMA edge at all (Pass 4a skips it because its qualifier IS
    the owner; 4d's prefix match misses it; 4d-gb's gate enumerates only
    GROUP BY + OCCURRENCE). Phase 4d-gc admits it ONLY when a qualified read
    that I2 resolved to `owner` in the SAME statement witnesses the field —
    and that witness is never owner-spelled, so the rule cannot witness
    itself. The gate is the clause set {MERGE ON, MERGE UPDATE SET, MERGE WHEN,
    MERGE INSERT, JOIN ON}, pinned by test, and the blast radius is pinned at
    exactly 7 edges corpus-wide. Principle: the same clause family produced 7
    real defects AND 7 false positives, and the witness — not the clause — is
    what tells them apart (a renamed USING projection has no alias-spelled read
    of the physical column anywhere in its statement).

53. **A TVF alias anchors on its own call line (M-T1, `EXTRACTOR_VERSION
    2026-08-28.11`; traceability R52)**: a table-function alias's def-site run
    `[name, alias]` is never adjacent — the call's parenthesized argument list
    sits between the function-name token and the alias — so the run matcher
    aborted on `(` and the alias anchored L0, silently no-op'ing every R37
    click and every edge highlight riding it. Opt-in `skip_parens` lets ONE
    balanced parenthesized group stand between two run tokens, bounded by the
    statement range; an UNTERMINATED group fails the candidate (never invents
    a line). Only the TVF alias's def site passes it — ordinary aliases keep
    the exact run forms they had, so no other anchor moves. (`.12` on top is
    V5's R46d continuation twins — arm roles + JOIN-ON AND legs.)

54. **The two opposite-direction walker admissions are fixed INSIDE the
    R-GATE, and `EXTRACTOR_VERSION` deliberately does not move (V7,
    shipped v3.3.195 — g1 over-inclusion + d2 over-filtering,
    `lineage._value_cone_gate`)**: **g1 (the G1-adjudicated residual,
    retired)** — a same-name REFERENCE edge between two field chips on
    DIFFERENT owner entities is the extractor's co-scope wiring
    (`build_dependency_graph` Phase 3's last-writer-wins `full_col_index`
    pick and its bare-name fallback), a graph-level FACT and not a value
    fact: the two endpoints are different FIELDS, so read as a producer
    claim ("the searched field's value comes from that foreign
    same-named column") it is false by construction — yet the cone
    crossed it twice, rule 4 admitting the foreign chip as the seed's
    producer and rule 6 then admitting the foreign chip's BOX, where
    rule 2 swept the chip in anyway. `_PHANTOM_COPY_GATE` gates BOTH
    crossings, and the phantom CLASS is removed with the edge: a foreign
    same-named chip no longer HOSTS a scope either (left in `_hosts` it
    justified its own statement's FROM leg through W6b and pulled its
    box in through the back door — the `src_b`/`⟐ s2` route). A
    cross-owner REFERENCE the consumer direction needs still crosses
    (the canonical `lending_ref↓SUP_M` closure carries the NOT-IN
    subquery's `DISTINCT lending_ref`@50 exactly that way) — the gate
    keeps `_rg_copy_pair(E) and E.target_id in A`. **d2 (over-filtering,
    the D2 write→read reader)** — a WRITE_READ edge is the READER
    statement's only leg and carries no write of its own, so no clause
    of `_leg_justified_b` justified it: rule 6 dropped a reader box the
    closure fixpoint had already admitted and the reader that references
    the searched field fell out of the served closure. The
    reader-statement clause now mirrors the walker's own forward
    WRITE_READ admit (`_tf in _stmt_field_parts`), so a reader that
    consumes the field joins and a reader that never touches it stays
    out. Both switches mirror `_VALUE_CONE_GATE`/`_OWNERLESS_SEED` (the
    switch IS the feature): every before/after assertion flips the
    gate's OWN switches, so the "before" side is the real previous
    engine, never a re-implementation. Blast radius measured: the
    flagship corpus is UNCHANGED (the jaccard benchmark stays
    1.0000/1.0000 on all 20 cases, none shrinks and none grows), the
    same equality holds over the five flagships' 1277 physical pairs and
    over the 108-script L2 snapshot corpus (41 expected-RED snapshots
    before and after — no new shift). **Why `EXTRACTOR_VERSION` stayed
    `2026-08-28.12`**: both fixes are walker-ADMISSION only and sit
    downstream of every cache key — the extractor's own output
    (variables, dependencies, the persisted model) is bit-identical, so
    a bump would have invalidated every analysis, evidence and model
    cache in every workspace for zero effect. Tests
    `backend/tests/test_v7_admission_fixes.py` (13).

55. **The canonical ground truth is RE-DERIVED from the SQL text, never
    reconciled with the engine (R46c/R46d, 2026-09-01) — the jaccard
    gate is 20/20 at 1.0000/1.0000 recall AND precision, and the two
    ruled-red `lending_ref` cases are GREEN**: R46c re-derived the
    `lending_ref↓SUP_M`, `iiapty↓SUP_M` and `lending_ref↑DL` rows FROM
    THE SQL TEXT row by row (the CR10 discipline — B is never read off
    the engine's emitted form) and removed **86 rows plus the 30
    canonical nodes the dropped chips fed (24 lending_ref + 6 iiapty)**,
    every removal carrying an inline `REMOVED (R46c … class Xn)` marker
    at its old site: **X1** sibling join-key operand legs (61 — the
    CONCAT/RPAD/`||` keys put the searched field on ONE side of the
    `=`, so the operand chip is that operand's own flow), **X2**
    sibling-field predicates (4), **X4** the rrcdm job-log trunk (4 —
    a bare `TOP{n}` context is not a scope, so W6b cannot justify a
    top-level trunk; this REVERSES the R29 row-level continuation pins
    of 2026-08-12 for those row pairs), **X5** a JOIN anchored at a
    projection line (`LFS41`/`LFS123`/`LFD2` — the LFS123 doctrine, now
    enforced by J1 Class 1), **X6** sibling write-zone legs and box legs
    with no field evidence (14). R46d (V5, `EXTRACTOR_VERSION
    2026-08-28.12`) mints each occurrence twin's OWN flow edge, so B
    gains the twin rows under the `e5tw` seed key — INERT IN THE GATE by
    construction (no `CASES` entry selects `e5tw`; adding one needs a
    `CASES` + `FLOORS` pair, the orchestrator's call). Point 24 of
    `tests/jaccard_canonical.py` CLOSES the CR10 "pending" ledger: every
    row whose form was an engine-emission convention is re-derived from
    the SQL text and its flag cleared (the flag MACHINERY stays); point
    25's audit adds the structural checks — no duplicate row (the one
    pair asserted twice, LFS117/LFS138, is the RULED G9
    instance-identity rendering), no unconsumed served edge, no
    unrealized canonical node. Residual, deliberately NOT absorbed into
    B: `sup↓SUP_M` prints 14/15 edges and `pl↓PL` 8/9 N / 9/11 E / 5/6 H
    until the engine owner repairs the R46d family-4 emissions (point
    23 — measured invariant to the gate AND to the fold, so the cause is
    the leg pass). The OLD canonical stays in git history; the two
    benchmark deselects this re-derivation made green were RETIRED from
    `release.sh` (commit `0ac1c81`).

56. **The physical-model build is 31% cheaper with a byte-identical
    model (H12, shipped v3.3.195 — `extractor/physical_model.py`)**:
    measured on RFN in situ the build was 45.8 ms and pass 3 (dependency
    edges) was 85.7% of it, the endpoint resolution re-deriving the same
    variable ~10× (20,674 calls for 1,953 distinct vars). **P1** memoizes
    `_var_ref` per var id (`_varref_memo`) — it is a PURE function of
    the var dict, `entity_of_id`, the label map and the entity table all
    FROZEN before that pass — and the memo is per build, so it cannot
    leak between builds. **P7** makes `PhysicalEdge` slotted (no
    per-edge `__dict__`, no longer a dataclass — measured first: no
    `asdict`/`fields`/`replace` use anywhere, no test compares two edges
    by value, one construction site) and LAZY: `flow_kind`/`reason`
    derive on FIRST ACCESS from `{"edge_type": …, **carried}` through the
    single_line strategy, computed once per edge and cached, while
    `highlight_line` stays EAGER (the strict walker and the lineage read
    it per edge). Nothing in the pipeline reads `flow_kind`/`reason`
    while building the model, so the eager derivation was pure waste.
    Net: **45.8 ms → 31.3 ms (−31.6%), model byte-identical** (the V6
    digest over the 10-script corpus). Minors measured and REJECTED: the
    P2 Mapping view and dropping the defensive copies — the model builds
    from SHARED analysis-cache dicts (the same dicts the L2 builder and
    the index read), and the copies are LOAD-BEARING: without them a
    later in-place mutation of a shared cache dict reaches the persisted
    model artifact. Tests `tests/test_physical_model_perf.py` (10, the
    structural invariants) + `tests/test_perf_byte_identical.py` (11).

57. **A ruled-red test is deselected at ALL THREE `release.sh` pytest
    sites, with the ruling citation — and retired the moment it goes
    green**: `release.sh` runs pytest three times (the host venv
    pre-flight, the `gps-sql-backend` pre-flight, the `gps-test` smoke
    stage), so a deselect added to one site only silently fails the
    other two — commits `e940782` → `05a3234` → `0ac1c81` are exactly
    that history being cleaned up. Current state: exactly TWO deselects
    per site, `tests/test_l1_physical_model.py::
    test_r29_lending_ref_downstream_matches_doc` and
    `…::test_r29_iiapty_downstream_matches_doc`, both red-documented
    PENDING the user's job-log-continuation edge-rule ruling
    (`wiki/FLOW_ONLY_VIEW_RULES.md` §7-A) and both citing it. They are
    DOC-conformance tests (the ground-truth doc still requires rows the
    canonical re-derivation removed), not benchmark tests — the former
    two lending_ref JACCARD deselects are GONE, retired by `0ac1c81` the
    moment R46c turned both cases green: a deselect that no longer
    carries a ruling is a lie the suite tells at every release.
    **RESOLVED 2026-09-01 (§7-A, USER RULING: "write leg only")**: when
    the searched field IS the column being written, its write edge shows
    even when the value is a constant; a field the log never writes gets
    NOTHING — the R29 always-continue row-level continuation is retired.
    Both R29 doc tests are GREEN (their assertions updated to the ruled
    reality with citations, the ground-truth docs repaired), so the
    deselect list is **EMPTY at all three `release.sh` pytest sites**, and
    the rule is now KEEP-IT-EMPTY: the list reopens only for a test that
    is red-documented PENDING a ruling, and a deselect whose ruling
    landed comes out the same day (`6001ef9`). Current gate: 1551 passed
    / 11 skipped / 0 failed / 0 deselected.

58. **The 2026-09-01 user rulings are ENFORCED in the engine, the walker is
    deterministic, and the deselect list is EMPTY (v3.3.197 — release
    `6c2ed1c`, feature commit `6001ef9`)**: three rulings landed, one
    canonical re-derivation, two product fixes — all measured.
    **(a) Rule 3a REVERSED + the sibling-chip prune**
    (`l2_builder._apply_field_involvement` **Class 3** +
    `_prune_orphan_sibling_chips`): a sibling's belongs-to edge is not
    the searched field's flow, so it is **DROPPED**, and the sibling chip
    the drop leaves with no edge at all is **PRUNED** — "If the sibling
    chips, which is not [the] searched target field, and doesn't have any
    edge, they are not contributing to the data flow. I think they should
    be removed" (the ruling is quoted in `wiki/FLOW_ONLY_VIEW_RULES.md`
    §3a). Flow-only views ONLY: the pass runs behind the search filter
    (`relevance_filter`), so a full view is byte-untouched — verified 0
    full-view diffs across all 32 changed snapshot baselines. The searched
    chip's OWN belongs-to and the R40.12 Reappears class never reach the
    branch (the seed-endpoint check keeps them).
    **(b) §7-A RESOLVED — WRITE LEG ONLY**: when the searched field IS the
    column being written, its write edge shows even when the value is a
    constant; a field the statement never writes gets NOTHING (the R29
    always-continue row-level continuation is retired). Measured to need
    NO engine change: the filter already served the searched field's own
    write leg (the only write leg it dropped corpus-wide was a
    sibling's), so the landing is tests + docs — 6 pinning tests, both
    R29 doc tests turned GREEN, `release.sh`'s deselect list EMPTY at all
    three pytest sites (#57).
    **(c) V8 walker determinism** (`lineage.py`): the closure walk's DML
    admission had ORDER-SENSITIVE side effects — the `_effect_cols`
    recording and the `_cont_cols` continuation fired on whichever edge
    class admitted the table first — so sorting the dependency list alone
    GREW the four `data_dt` cases. Fix: every node's adjacency is walked
    in a canonical content order (`_WALK_RANK` = the expansion loop's own
    rule precedence), the frontier and the bulk rounds iterate
    registration order, `_seed_comp` takes the canonically-first seed, on
    top of the canonical dependency sort — and with BOTH halves the four
    `data_dt` cases return to exactly their pre-sort served sets.
    `tests/test_l2_determinism.py` (SEEDS `0/1/2/3/7`) is a **HARD GATE**
    — the xfail is removed — and, since the coordinator's REVIEW-F1
    extension, it covers BOTH the full view and the flow-only view:
    a server restart can no longer serve differently-chosen graphs.
    **(d) Canonical point 26**: `tests/jaccard_canonical.py` docstring
    point 26 re-derives both rulings FROM THE SQL TEXT (CR10) — 5 edge
    rows (LFS135, LFS143-145, LFD1) + 3 canonical node entries removed,
    the searched field's OWN belongs-to rows STAY, and every removal
    carries an inline `REMOVED (USER RULING 2026-09-01 …)` marker at its
    old site. The floors are untouched — 20/20 at 1.0000/1.0000.
    **(e) P2 product fixes**: `auth_service` serializes the `users.json`
    read-modify-write under one `threading.RLock` (`_users_lock`, spanning
    load → mutate → save) so two concurrent writers can no longer
    interleave and drop each other's entry; and a creator's PHYSICAL
    workspace delete purges it from EVERY user's index
    (`remove_ws_from_all_indexes`), not only the caller's. Housekeeping:
    `EXTRACTOR_VERSION = "2026-08-28.13"` + one snapshot rebaseline (103
    of the 108 baselines re-pinned; content sets identical, keeper
    re-picks rehash ids only). Gate: **1551 passed / 11 skipped / 0 failed
    / 0 deselected / 0 xfailed**, jaccard **20/20 at 1.0000/1.0000**.
