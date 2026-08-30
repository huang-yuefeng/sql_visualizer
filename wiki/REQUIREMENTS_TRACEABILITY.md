# Requirements Traceability Matrix — V3.3.190

> Maps all requirements from REQUIREMENTS.md to implementation status.
> Last updated: 2026-08-29 (R44 LANDED + the 2026-08-28 code review adjudicated + the 50-target user-scenario simulation. R44.1 flipped ⏳ → ✅ — occurrence coverage is implemented: write-side/derived-read twins, GROUP-BY twins (`_register_groupby_twins`), OVER-line WINDOW anchors (`highlight_strategies._anchor_line`), l2_builder write-target parenting, R45's family-3 occurrence-line twins (`_collapsed_occurrences`); `EXTRACTOR_VERSION 2026-08-28.3 → 2026-08-28.7` (.7 = the K4 paren-balance diagnostics bump). R44.2/R44.3 stay ⏳ (benchmark re-pin + unified snapshot regeneration). NEW rows: R2.11 (backend case-insensitive search — R2.10's F5 was FRONTEND-ONLY before), R5.13 (#386 CTE statement-scoped visibility ruling), R13.7 (simulation-driven sample repairs), R37.5/R37.6 (K4 VT-anchor amendment / F-B1 field-chip + banner + direction-flip fixes — ⏳), R40.11 (F-B2 chip-decoration guard + banner/autocomplete UX), R44.4 (filter-operand twin edges, F-E1 — ⏳). NEW sections: "K4 rulings (2026-08-28)" and "User-scenario simulation (2026-08-29)". The 2026-08-28 code review's 31 first-pass findings are FULLY ADJUDICATED (23 fixed / 6 false positives / 2 deferrals) — verdict table in `wiki/CODE_REVIEW_2026-08-28.md` §"Resolution status (2026-08-29)". CLAUDE.md's #23/#28/#29 amendments are owned by the F-B1 team and are NOT recorded here yet (pending). Prior 2026-08-28 (v3.3.191+ batch recorded — PENDING RELEASE, landed in the working tree: R40.8 + R41.1/R41.2 flipped ⏳ → ✅ (self-loop curve geometry via data-driven `loopstep`; minZoom 0.28 → 0.08 + `min-zoomed-font-size` 6 + Fit suppresses the seed re-center); new rows R2.9 (F2 CTE index defining-script invariant), R2.10 (F5 case-insensitive name resolution), R5.12 (MERGE targets join the physical fold, #386), R13.6 (RFN sample fully OCR-recovered, #370 — all four samples clean), R40.10 (Field Story Joined/Transformed stage); R40.9's open ruling #380 RESOLVED (creator-only scan/index, 403 participants); R44 added ⏳ (walker occurrence coverage — in flight, NOT yet landed); R43.4 note extended (unified snapshot regeneration at release). Prior 2026-08-28 (R40–R41 added — L2 readability batch v3.3.187–v3.3.190 shipped: filter loop-line anchored to the table border, zoom-compensated caption, Field Story step-through bar, flow-reason panel REMOVED + bar relocated below the SQL panel, cache headers, history slim (re-clone required); multi-user matrix 14 scenarios green with ONE open ruling (#380 index/scan not creator-gated); R40.8 same-table edge + R41 zoom-floor/Fit fixes IN FLIGHT. Prior 2026-08-27 (R33–R36 added ✅ — hover label emphasis, view-open search-params recovery, fit readability margins + zoom floor, release pipeline static-sync guard; shipped v3.3.171–v3.3.178. Prior 2026-08-26 (R32.1–R32.3 flipped ⏸ → ✅ — line-merged views shipped v3.3.166; R1.8 #308 + R31.2 M-Po4 flipped 📝 → ✅ — closed v3.3.165; R31.1 annotated superseded by #293; R31.9 annotated deleted by #322; version bumped to 3.3.166. Prior 2026-08-25: R31 status markers reconciled with shipped code — 8 previously-📝 rows flipped to ✅ against verified implementation; summary recounted: 169 implemented / 1 partial (R31.2 IP audit, pending M-Po4); version bumped to 3.3.164. Prior 2026-08-24: #288/#289 L2 graph backend fixes — case-insensitive physical-table merge shipped; #289 INSERT write-column routing corrected to be a model-following fallback (write columns land on their physical-model owner; only phantom-sourced columns land on the write target); #286 R31 regression fixed — dashboard folder upload restored; R31 status → released v3.3.162, E-series review fixes pending)

## Legend
- ✅ Implemented & verified
- ❌ Not yet implemented
- ⏳ In flight — fix being implemented / queued, not yet verified

---

## R1 — Folder Upload & File Tree (from requirements_v2.md §1)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R1.1 | Upload folder (zip) | ✅ | Upload .zip button works |
| R1.2 | Direct folder upload (no zip) | ✅ | "Select Folder" (webkitdirectory + JSZip client-side packing) is available on BOTH the dashboard (`MyWorkspaces.jsx`) and the debugger (`WorkspacePanel.jsx`). #286: R31 released v3.3.162 zip-only on the dashboard, which hid the picker behind the debugger (unreachable on a fresh account — chicken-and-egg); restored 2026-08-24 |
| R1.3 | Hierarchical file tree display | ✅ | FolderTree component in left panel |
| R1.4 | SQL files clickable, non-SQL grayed | ✅ | is_sql flag, non-SQL dimmed and not clickable |
| R1.5 | Multi-select scripts/folders with checkboxes | ✅ | Checkboxes with [deselect all] |
| R1.6 | Multiple users, separate workspaces | ✅ | UUID workspace IDs |
| R1.7 | Extract tables/fields as search indexes | ✅ | tableIndex, fieldIndex from all selected scripts — scope = **physical tables/fields only** (2026-08-25 ruling: search retrieves data-flow errors, visible only on physical tables/fields) |
| R1.8 | Search scope = real physical tables/fields only | ✅ | #308 (M-S1 / D-M1) — closed v3.3.165 — folder_index Fix A curation ships the physical tables/fields-only search scope (derived/computed aliases no longer leak via the `source_tables[0]` fallback) |

## R2 — Filter Panel / Search (from requirements_v2.md §2)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R2.1 | Table name autocomplete | ✅ | Physical tables only (2026-08-25 ruling); color-coded dots per table |
| R2.2 | Field name autocomplete | ✅ | Physical fields only (2026-08-25 ruling); table-colored dots from associated table |
| R2.3 | Table-first input: select table → field dropdown shows table's fields | ✅ | getFieldOptions() filters by selected table |
| R2.4 | Field-first input: type field → table dropdown shows tables containing it | ✅ | getTableOptions() filters by selected field |
| R2.5 | Search button triggers L1 view | ✅ | Enter key also triggers search |
| R2.6 | Narrow Index (CSV filter: script-table + table-column files) | ✅ | Upload ST/TC CSVs to filter autocomplete index |
| R2.7 | Search history (recent 10) | ✅ | 🕐 Recent dropdown |
| R2.8 | Pinned searches (star) | ✅ | ☆ / ★ toggle, appears in Pinned section |
| R2.9 | **F2 (audit #383) CTE index entries carry their defining script** — a CTE's table_index row received fields but never the script, so the search intersection `field_index[f].scripts ∩ table_index[t].scripts` was EMPTY and qualified CTE lookups (TEMP_RFN, temp_kmbh_*) found nothing | ✅ | 2026-08-28 (pending release) — invariant installed at THREE attribution sites in `folder_index_service.py` (CTE-name branch, field-branch, write-target branch): fields recorded from a script imply `table_index[tname]["scripts"].add(rel_path)`; +6 tests (`tests/test_folder_index_cte.py`); the unqualified-only CTE ruling is PRESERVED (bare/unqualified-only CTE names stay out); 128 regressions green |
| R2.10 | **F5 (audit #383) case-insensitive name resolution** — a typed name in ANY casing must resolve against the index (SQL identifiers are case-insensitive; index keys carry whatever casing each script wrote, e.g. TEMP_RFN vs temp_rfn), with a canonical echo + an inline "no such table.field in the index" message instead of the silent no-op | ✅ | 2026-08-28 (pending release) — `resolveNameCi()` in `utils/nameFilter.js` (exact key wins; case-insensitive equals ranked with the dropdown's collation — deterministic); FilterPanel echoes the canonical key and shows the inline not-in-index message on a null resolution; +10 tests (nameFilter +5, FilterPanel +5). **2026-08-29 (F5-extension, R2.11): F5 was FRONTEND-ONLY — the backend still matched index keys exactly** |
| R2.11 | **F5-extension (2026-08-29, user-scenario simulation finding) — the BACKEND resolves search names case-insensitively too**: `resolve_name_ci` in `folder_index_service.py` is now the single resolution point for `create_search` and the `POST .../search` router (plus `scripts_for_name_ci`), so a workspace whose scripts spell the same table/field with different casing (TEMP_RFN vs temp_rfn) no longer produces disjoint case-variant index keys that make a correct-looking search return `no_matches` | ✅ | 2026-08-29 (pending release) — Team F-A. `folder_index_service.resolve_name_ci` (line ~1579) + `create_search` (`dataflow_service.py:87-88`) + the search router (`routers/dataflow.py:136`) all resolve through it; the same canonical-key + group model as the frontend's `resolveNameCi` (R2.10), so both sides now agree on ONE canonical key per identifier |

## R3 — View Management (from requirements_v2.md §3)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R3.1 | View management tree/bar | ✅ | ViewBar with tabs |
| R3.2 | L1 view = all scripts related to table.field | ✅ | Shows script count badge |
| R3.3 | L2 view = single script detail (child of L1 view) | ✅ | Double-click script node → L2 |
| R3.4 | Remove individual views | ✅ | × button on each tab |
| R3.5 | Multiple concurrent searches | ✅ | Each search creates new view tab |
| R3.6 | + New Search button | ✅ | ViewBar component |

## R4 — L1 Graph: Script-level Data Flow (from requirements_v2.md §4)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R4.1 | Script nodes as orange rounded cards | ✅ | SCRIPT_CARD_STYLES, type="script_node" |
| R4.2 | Data flow edges between scripts (directed) | ✅ | table_script edges |
| R4.3 | Click script node → open L2 graph for that script | ✅ | Double-click handler → handleOpenL2 |
| R4.4 | Directional arrows on all edges | ✅ | target-arrow-shape: triangle on all edge styles |
| R4.5 | Tooltips on edge hover showing type + description — REMOVED (see R30.7) | ✅ | Shared L1+L2 edge-hover tooltip (`edgeHover` state + `.edge-tooltip` div) REMOVED v3.3.159 (#240, commit a77dfdd) — one shared feature, so the popup no longer appears on EITHER level; the L2 edge-click flow-cone + edge→SQL highlight are separate handlers, unchanged — see R30.7 |
| R4.6 | Operation badges on script nodes showing roles | ✅ | Roles (REF/JOIN/FILTER etc.) appended to node label |
| R4.7 | Source/Intermediate/Output table coloring | ✅ | Table nodes colored by role in legend |
| R4.8 | Fit/Zoom controls | ✅ | Fit button + keyboard shortcut F |
| R4.9 | Export graph as PNG | ✅ | 📷 button |
| R4.10 | Minimap toggle | ✅ | 🗺 button |
| R4.11 | L1 = the queried field's data flow — same field-level semantic as L2 — at cross-script scale (scripts + tables between scripts, no fields) | ✅ | R29 (2026-08-12) — implemented v3.3.153 |
| R4.12 | No table-level inclusion: scripts/tables that only read or write the queried TABLE are excluded | ✅ | R29 (2026-08-12) — v3.3.153 — e.g. SUP_M for a BNQXYE search |
| R4.13 | ~~Direction = query panel setting (upstream = writing, default / downstream = reading)~~ **AMENDED R38 (2026-08-27): toggle REMOVED — every search runs downstream (reading flow), the only direction** | ✅ | R29 v3.3.153 → R38 ruling |

## R5 — L2 Graph: Table/Field-level Data Flow (from requirements_v2.md §4-5)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R5.1 | Table nodes with field children (compound nodes) | ✅ | source_table, intermediate_table, output_table + field children with parent |
| R5.2 | Direct vs indirect field grouping | ✅ | field_group: "direct" (on BFS path) / "indirect" (off-path) |
| R5.3 | Edge type color coding (7 categories) | ✅ | CATEGORY_EDGE_STYLES: copy/compute/aggregate/filter/combine/write/structure |
| R5.4 | Category mapping from 16 edge types → 7 categories | ✅ | CATEGORY_MAP in dataflow_service.py |
| R5.5 | Toggle full/related view | ✅ | Show All / Show Relevant button |
| R5.6 | Click edge → highlight SQL segment | ✅ | Edge click sets sqlHighlightRange |
| R5.7 | Target field node (gold highlight) | ✅ | is_target with gold border |
| R5.8 | CTE table nodes (dashed green) | ✅ | cte_table style |
| R5.9 | L2 follows the query direction automatically — zoom-in of L1's directional flow, no separate control **(R38: that direction is now always downstream)** | ✅ | R29 v3.3.153 → R38 ruling |
| R5.10 | **#288 L2 physical tables merge CASE-INSENSITIVELY into one compound node** — east5_stzfxxb / EAST5_STZFXXB previously split into 2 nodes | ✅ | #288 (2026-08-24) — Team C backend — the physical-table merge key is case-folded (one keeper, merged-away nids re-point via occ_to_id, edges re-pointed); aliases / CTEs / subqueries stay case-sensitive — a case-twin alias (A vs a) is still a DIFFERENT alias node. Tests: `tests/test_l2_case_merge.py` |
| R5.11 | **#289 INSERT write-alias columns render ON the write target node** — but only as a FALLBACK: a SELECT-projection column sourced to a phantom alias (no real model owner) lands on the write target; a projection sourced to a real table/CTE/alias renders on that source (its physical-model owner), keeping the display a pure projection of the model | ✅ | #289 (2026-08-24, Team C) + Team E correction 2026-08-24 — each statement's ⟐-output SCHEMA members (its SELECT projections) re-parent onto that statement's DML write target's keeper compound ONLY when the projection has no visible source parent; the physical model is the independent truth — write columns sourced to a real table render on that owner, not on the target (nbjgh→bdm_acc_loan_info, internal_key→loan_final, LENDING_REF→ods_ccb_cb_loan_acctloan), while phantom-sourced projections (bz, TAG_*, RESERVED_*, PRIMARY_SRC_SYSTEM) render on the target. DML ⟐-output routing untouched (no qo_ nodes, write legs still hang off each statement's own output VT). Tests: `tests/test_l2_case_merge.py` |
| R5.12 | **#386 (2026-08-28) MERGE targets join the physical fold** — the table-duplication audit's ONE real bug: a table that is MERGE-INTO'd in one statement and read/written in another rendered as TWO compound nodes; the model already keys a MERGE target by its raw name (kind physical, roles {merge_target, read}), so its occurrences must merge into the one keeper | ✅ | 2026-08-28 (pending release) — `l2_builder.py` physical fold admits merge_target occurrences (2 conditions; aliases excluded); +3 T3 regression tests in `tests/test_l2_case_merge.py` (fold, read-first order, and 1-char-apart tables stay distinct). Adversarial cases prove schema/backtick/case twins were ALREADY folded and 1-char-apart tables NEVER over-merge. Four #386 rulings filed (CTE-shadows-physical stays separate; RFN typo pairs are real distinct tables; RFN duplicated INSERT block is deliberate sample content; alias-label collisions informational) — see `wiki/CODE_REVIEW_PENDING_2026-08-27.md` §5. **Ruling 5 added 2026-08-28 (CTE scope) — see R5.13** |
| R5.13 | **#386 CTE-scope ruling — a CTE's name is visible only inside its own statement (SQL-standard scoping)**: a LATER statement's bare reference to a CTE's name registers a PHYSICAL table read; it is never swallowed by the any-context CTE merge | ✅ | 2026-08-28 (`EXTRACTOR_VERSION 2026-08-28.4`, item 4) — `_add`'s CTE merge is scope-aware via `_is_cte_name` (statement-scoped visibility; in-scope refs keep folding). The model still matches owners by the SHARED `name` string (`_name_to_key` — a CTE and a same-named physical table collide there), so `l2_builder` disambiguates at DISPLAY time via `_stmt_root` (the in-scope CTE compound) and `field_owner_key` (the field's occurrence-owner entity): the out-of-scope read's columns land on the PHYSICAL compound, never on the `cte_table` node |

## R6 — SQL Panel & Export (from requirements_v2.md §6)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R6.1 | SQL text panel for L2 script | ✅ | SqlPanel component |
| R6.2 | Highlight data flow related SQL lines | ✅ | sqlHighlightRange + highlight set |
| R6.3 | Auto-scroll to highlighted section | ✅ | scrollIntoView on first highlighted line |
| R6.4 | Export SQL button | ✅ | ⬇ Export button downloads .sql file |
| R6.5 | SQL export configuration panel | ✅ | ⚙ Config with 10 toggleable options |
| R6.6 | Upload JSON config file | ✅ | "Upload Config (JSON)" button |
| R6.7 | Default config when none uploaded | ✅ | DEFAULT_CONFIG object (10 options) |
| R6.8 | Editable config values (click to edit) | ✅ | Context lines slider, dialect dropdown, bool toggles |
| R6.9 | Config auto-save per workspace | ✅ | Debounced save to backend |

## R7 — Legend (from REQUIREMENTS.md §R3)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R7.1 | Node type legend (14 node types) | ✅ | DataFlowLegend with L1_LEGEND + L2_LEGEND |
| R7.2 | Edge type legend (7 categories) | ✅ | CATEGORY_LEGEND: copy/compute/aggregate/filter/combine/write/structure |
| R7.3 | Full 16 edge type legend | ✅ | EDGE_LEGEND with all 16 edge types |
| R7.4 | Color-coded by category | ✅ | Each category has distinct color + line style |

## R8 — General UX
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R8.1 | Data Flow Debugger as first/default tab | ✅ | AppShell default mode='dataflow' |
| R8.2 | Legacy SQL Analysis tab preserved | ✅ | PersistentPanel, never unmounted |
| R8.3 | Dark/Light theme toggle | ✅ | ☀️/🌙 button |
| R8.4 | Keyboard shortcuts (Esc, F) | ✅ | Esc=go L1, F=fit graph |
| R8.5 | Responsive three-panel layout | ✅ | Left sidebar, center graph, optional inline L2 |
| R8.6 | Loading skeleton animation | ✅ | Skeleton nodes/edges during loading |
| R8.7 | Error banner with dismiss | ✅ | Red error banner, click to dismiss |

## R9 — Data Flow Formal Definition (from REQUIREMENTS.md)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R9.1 | 15 variable types extracted | ✅ | variable_extractor_v2.py: table/view/cte/subquery/virtual_table/merge_target/union_branch/column/cte_column/aggregate/window/case/transform/expression/literal |
| R9.2 | 16 edge types in dependency graph | ✅ | TABLE_FLOW/ALIAS/REF/AGGREGATE/TRANSFORM/WINDOW/COMPUTED/SCHEMA/INDIRECT/FILTER/JOIN/CORRELATED/DML/SET_OP/SUBQUERY/SUBSET |
| R9.3 | Node identity = (name, type, context) triple | ✅ | Deduplication by triple |
| R9.4 | 7 edge categories for visualization | ✅ | copy/compute/aggregate/filter/combine/write/structure |
| R9.5 | BFS-based direct/indirect classification | ✅ | Upstream + downstream BFS from target nodes |

## R10 — Node Type Per-Type Coverage (53 tests)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R10.1 | 53 node type coverage tests | ✅ | tests/test_node_per_type.py |

## R11 — Edge Type Per-Type Coverage (36 tests)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R11.1 | 36 edge type coverage tests | ✅ | tests/test_edge_per_type.py |

## R12 — Key Bug Fixes
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R12.1 | qo_ node eliminated | ✅ | v3.3.71 — Simplification 1 |
| R12.2 | Edge range overlap reduced | ✅ | v3.3.72 |
| R12.3 | Compound edge types split | ✅ | v3.3.69 |
| R12.4 | Alias detection via semantic analysis | ✅ | Bug 5 fixed v3.3.67 |

## R13 — Sample Library
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R13.1 | multi_workflow sample | ✅ | 5-script pipeline |
| R13.2 | multi_test sample | ✅ | GPS transactions |
| R13.3 | tpcds_qualified sample | ✅ | 103 TPC-DS scripts |
| R13.4 | dialect_test sample | ✅ | BigQuery/MaxCompute/Snowflake |
| R13.5 | financial sample | ✅ | 18 financial scripts |
| R13.6 | **#370 RFN sample fully OCR-recovered** — `BDM_ACC_LOAN_INFO_RFN.sql` re-derived from the surviving screenshots with the committed OCR harness + targeted pixel-topology-glyph reads; all 21 `OCR-UNCERTAIN` markers resolved with evidence (21 → 0 across the 13 case2 screenshot pages); two bonus finds (restored missing `rrcdm` INSERT header @L1396); gates green (parse_errors 0, jaccard 1.0000, snapshot 02 regenerated with a 1:1-audited delta + changelog entry). ALL FOUR samples now carry zero markers | ✅ | 2026-08-28 (pending release) — `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql` + `SNAPSHOT_CHANGELOG.md` 2026-08-28 entry (RFN is not a benchmark seed) |
| R13.7 | **Simulation-driven sample repairs (2026-08-29)** — two pixel-evidenced repairs found while walking the 50-target user scenario: RFN gains the 2 missing closing parens its screenshot shows (the surrounding predicate block was unbalanced), and PL drops the stray `;` at L19 that split a statement | ✅ (re-pin pending) | 2026-08-29 — repairs are in the samples; the PL repair moves 3 `jaccard_canonical` rows, and that re-pin is IN FLIGHT (see R44.2 / `SNAPSHOT_CHANGELOG.md` DRAFT entry). Sample edits never mask engine defects: the 2026-08-28 review's H3 (RFN L492 empty-literal join key) and M9 (RFN L351 `OR`) were checked against the same pixels and stand as written — both are FALSE POSITIVES |

## R14 — Server-Side Progress Logging
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R14.1 | SSE endpoint for pipeline logs | ✅ | `/api/logs/{ws_id}/stream` |
| R14.2 | LogPanel with collapsible display | ✅ | Frontend LogPanel component |
| R14.3 | Color-coded stages | ✅ | Indexing/Search/Graph stages |
| R14.4 | Thread-safe queue.Queue | ✅ | backend/app/services/logger.py |

## R15 — Script Profile Summary
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R15.1 | ASCII-box diagnostic block | ✅ | Size/Lines/Stmts/Clauses/Funcs/Vars/Edges/Nesting/Timing |
| R15.2 | Emitted after pipeline completion | ✅ | SSE log stream |

## R16 — Filter CSV Diagnostic Logging
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R16.1 | Filter CSV diagnostic output | ✅ | Scope table, row counts, mismatch warnings |
| R16.2 | Two-way CSV path matching | ✅ | Bug 15 fixed v3.3.89 |

## R17 — Search Diagnostic Logging
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R17.1 | Search diagnostic after filter | ✅ | Scope tables, field counts, filter stats |

## R18 — Field-Level Data Flow Extraction
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R18.1 | compute_field_lineage BFS | ✅ | 16 edge-type rules in lineage.py |
| R18.2 | filter_relevant graph filtering | ✅ | L1 + L2 filtering wired |
| R18.3 | infer_table_schemas (7-pass) | ✅ | schema_inference.py |
| R18.4 | lineage_mode in create_search | ✅ | Default True |
| R18.5 | original_id bridge (L1 ↔ analysis) | ✅ | Bug 19 fixed v3.3.103 |
| R18.6 | table_schemas on cache hit/miss | ✅ | Bug 20 fixed v3.3.103 |
| R18.7 | L1 filter = the SAME strict field-level walker as L2 (not the table-level production BFS) | ✅ | R29 (2026-08-12) — v3.3.153 — supersedes R18's L1 semantics |

### R18.1 — Empty Table Cleanup
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R18.1.1 | Remove tables with 0 field children | ✅ | v3.3.105 — primary + fallback paths |
| R18.1.2 | Keep termination marker table | ✅ | v3.3.105 — terminal table + edge preserved |
| R18.1.3 | L1 terminal-marker rules superseded — the flow terminates at the last table carrying the queried field; no marker table | ✅ | R29 (2026-08-12) — v3.3.153 — L1 side only; L2 unchanged |

## R19 — L2 Flow Topology: one source, flow targets, every edge on a path (user ruling 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R19.1 | The filtered L2 flow view has exactly one flow source: the searched table.field (the seed) | ✅ 2026-08-11 | v3.3.140 seed semantics — the closure root; the source is USER-DEFINED (the search), never inferred. Wave 2 exposes it: `flow_source: true` on the seed's table keeper in the L2 node data (lineage.py `flow_source_id` + l2_builder wiring, v3.3.150). In the full view (no search) origins = read-only tables (read, never written in the script) |
| R19.2 | The flow targets are the output tables the seed's data reaches (DML write targets; pure-SELECT scripts: the terminal output VT). One or more — e.g. the bdm seed reaches sup@160 AND rrcdm@211 | ✅ 2026-08-11 | DECISION PROCEDURE implemented (lineage.py `flow_targets`): T is a flow target iff (a) T is a DML statement's write target (extraction-time DML attribution) AND (b) T's write leg `output → T` is in the seed's flow closure. Verified: bdm seed → sup + rrcdm ✓; sup seed → sup (self, mechanically — its own write leg is in its closure) + rrcdm. Exposed as `flow_target: true` on target table keepers (v3.3.150) |
| R19.3 | Topological property: every flow edge lies on ≥1 path from the source to some target; no dead-end flow branches; no-bypass — cross-statement flow must route through the reader instance, never shortcut around it | ✅ 2026-08-11 | asserted in the Jaccard gate (`R19_3_CHAIN` incidence checks, Wave 1); Issues 2/3 removed the bypass — the chain routes write→sup@160 → read sup@223 → output → rrcdm@211 through the reader |
| R19.4 | Structure/containment edges (SCHEMA) are NOT flow — exempt from the path property, rendered visually distinct, their reason explains containment (owner→member by design) | ✅ 2026-08-11 | by-design exemption, never forced onto a flow path; **display toggle implemented (frontend, v3.3.150)** — hidden by default in the flow view, payload + benchmark unchanged (`structureEdges.js` + `useCytoscapeGraph` `structure-hidden` class, legend note + edge-count reflect it) |
| R19.5 | Full-view (no search) table roles: net-flow classification — a table is a source when flow out dominates (out-edges > in-edges over FLOW edges only, self-loops excluded), a target when flow in dominates; multiple of each; balanced tables = waypoints | ✅ 2026-08-11 | implemented (lineage.py `classify_flow_roles` + l2_builder `flow_role` on physical table compounds, v3.3.150). ⚠ example repaired with evidence: sup is NOT balanced in the real full view — **5 in** (write leg TABLE_FLOW + 2 COMPUTED + REF data_dt→sup + FILTER data_dt→sup) / **3 out** (read-leg TABLE_FLOW + REF sup→p2@199 + JOIN) → **target**. Waypoints are realized by balanced tables (a@132, b@133, c@137, p1@198, p3@118, p3@204, p5@151, p6@155). Rule unchanged (user wording); flow = every edge type except ALIAS/SCHEMA/SUBSET (TABLE_FLOW counts — read legs and L2 write legs are TABLE_FLOW; the `category` field is NOT consulted: L2 chain edges carry category=structure yet are flow) |
| R19.6 | No inverse edges in the flow view: (a) structure/containment edges hidden by default (display toggle; payload + benchmark unchanged); (b) synthetic output VTs un-merged by statement (output@L160 / output@L211) so write/read leg pairs never render as inverse — R22 one-node-per-table narrowed to PHYSICAL tables | ✅ 2026-08-11 | (a) the R19.4 toggle (frontend, default off); (b) probe-verified already true — the served L2 graph carries TWO distinct output VTs (`l2_tbl_7b217fb63a` TOP0@L160, `l2_tbl_236587aa4c` TOP1@L211), R22's label-keyed merge never merges per-context VTs; no code change needed for (b) |
| R19.7 | Source/target anchoring follows the query direction (user ruling 2026-08-12, R29): downstream → the queried field is the flow SOURCE (R19.1 unchanged); upstream → the queried field is the flow TARGET — the flow converges on it, sources = the fields writing it | ✅ | R29 (2026-08-12) — v3.3.153 — L2 flow-reason roles flip with the query direction |

## R20 — Path-Scoped Flow Reason (user ruling 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R20.1 | Every flow edge's reason renders the edge within its complete source→target path: `source@L… → … → ‖own segment‖ → … → target@L…` — upstream walk + downstream continuation, own segment emphasized (existing ‖…‖ wrap) | ✅ 2026-08-11 | implemented (v3.3.150): build-time path computation in l2_builder (`_closure_walk` upstream from the seed closure + `_downstream_walk` to exhaustion over final flow edges, bracket rule attributes each edge to its own statement's write target), carried as `_path_hops`/`_own_seg_idx` and rendered by `_build_reason` — `kind (role) — src@L… → … → ‖own‖ → … → tgt@L…`, own segment ‖…‖-wrapped mid-path. SCHEMA/SUBSET/leaf/pre-R20 carriers keep the plain `kind — flow string` form (byte-identical fallback) |
| R20.2 | The reason explains the edge's role in the scope of its path (write leg / read into output / alias hop / CTE chain …), derived from extraction-time info — never reconstructed at render | ✅ 2026-08-11 | implemented (v3.3.150): `_path_role` in highlight_strategies from extraction-time info only (`_dml_origin`/`_value_edge` → write leg / write value, `_tgt_output`/`_tgt_is_vt` → read into output, `_op` → alias hop / filter step / join step / CTE chain …); `kind (role) — path`. Rendered by the frontend's EdgeReasonPanel (‖…‖ split, tolerant of longer strings) |

## R26 — Remove code evidence from the Flow Reason panel (requirement change, 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R26.1 | `EdgeReasonPanel` renders ONLY edge kind, anchor line, and the R25 reason string (with the ‖…‖-emphasized current-edge segment) — no `mech` sentence, no evidence rows, no `onJumpToLine` prop | ✅ 2026-08-11 | implemented: `frontend/src/components/EdgeReasonPanel.jsx` rewritten (signature `{ edge, height }`); mech block + `onJumpToLine` deleted; backend `mech` payload fields, if any, are simply ignored by the panel. `EdgeReasonPanel.test.jsx` R26 pin test replaces the R11-3 mech/evidence suite |
| R26.2 | Edge click keeps highlighting + scrolling the anchor line in the script panel (existing R25 behavior — unchanged) | ✅ 2026-08-11 | highlight/scroll path unchanged; `DataFlowApp.jsx` dropped `sqlPanelRef`/`handleJumpToLine` (the panel no longer needs them) |
| R26.3 | Backend `mech` payload emission: retention decision deferred to the integration turn — remove only if no consumer remains (no-dormant-machinery rule); the UI change is the requirement | ✅ 2026-08-11 | backend `mech` payload DELIBERATELY RETAINED — `l2_builder.py` `_build_mechanism`/`_mech_sentence`/`_mech_fallback_clause` still emit (integration turn may drop it later); no backend change in this batch |
| R26.4 | Empty state ("Click an edge…") unchanged | ✅ 2026-08-11 | constant-height empty state preserved in the rewritten panel |

## R27 — Line numbers after node names in the L2 graph (requirement change, 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R27.1 | Frontend-only label decoration — append `@L{line_start}` to the RENDERED label of L2 nodes (table compounds, field nodes, `⟐ output` VTs); payload label untouched → gate-neutral (canonical node realization matches payload labels; display = pure projection) | ✅ 2026-08-11 | new `frontend/src/utils/labelDecoration.js` — `decorateLabelWithLine(label, lineStart)`; applied in `hooks/useCytoscapeGraph.js` L2-only (isL2 guard) BEFORE the S/T/W badge block; payload labels untouched |
| R27.2 | No double-append — nodes whose backend label already ends with `@\d+` (aliases `p1@29`, `p2@199`, …) keep it as-is | ✅ 2026-08-11 | `@L?\d+$` trailing guard — no `@29@29`; also idempotent for labels already carrying `@L<digits>` |
| R27.3 | Compounds (one node, many occurrences) show the node's carried `line_start` (keeper/first occurrence, e.g. `bdm_acc_loan_info_sup@160`); per-occurrence lines remain on the edges (R25). Documented limitation, not a defect | ✅ 2026-08-11 | decoration uses the node-carried `line_start`; limitation documented in the labelDecoration.js header comment |
| R27.4 | Output VTs render `output@160` / `output@211` — exactly the reason-string convention | ✅ 2026-08-11 | same decoration path covers the `⟐ output` VTs (line_start 160/211) |
| R27.5 | L1 labels unchanged (L2 only, per the user's ask) | ✅ 2026-08-11 | `isL2` guard in useCytoscapeGraph.js — L1 never decorated; zero payload change (backend untouched) |
| R27.T | Vitest coverage — append / no-double-append / keeper-line-for-compounds | ✅ 2026-08-11 | `utils/__tests__/labelDecoration.test.js` — 6 tests, all green; frontend suite 11 files/115 tests → 13 files/122 tests, all green |

## R28 — L2 node legend replaces the edge legend (requirement change, 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R28.1 | L2 legend = node roles: Source node (the searched table — the flow's start), Target node (flow destinations / output tables), Waypoint (intermediate tables on the flow path); source and target the emphasized entries | ✅ 2026-08-11 | `DataFlowLegend.jsx` L2 branch renders `L2NodeRoleLegend` (Source node / Target node / Waypoint, emphasized source+target); `FlowKindLegend` + `FLOW_KIND_GROUPS` deleted (no references remain outside tests) |
| R28.2 | Distinct visible node styles for source/target/waypoint in L2 — renderer reads the payload (`flow_role` "source"\|"target"\|"waypoint" on table compounds (full view), `flow_source`/`flow_target` booleans (filtered view), `is_target` on seed-copy nodes), never guesses | ✅ 2026-08-11 | new `L2_ROLE_COLORS` + `L2_NODE_ROLE_STYLES` in `frontend/src/utils/graphStyles.js` — source #5DADE2, target #58D68D, waypoint #7a7a9a; styles appended LAST so they win selector ties |
| R28.3 | The L2 edge legend is removed; edge flow-kind midpoint labels (R25 rule 5) remain — the hover tooltip (edge type, counts — R25 secondary surface) was REMOVED | ✅ 2026-08-11 | L2 edge legend gone; midpoint labels remain; hover tooltip REMOVED v3.3.159 (#240) — see R30.7 |
| R28.4 | L1 legend unchanged; the SCHEMA-structure note (hidden-edge count, structure toggle) stays reachable | ✅ 2026-08-11 | L1 legend unchanged; structure note kept as a footnote under the L2 node legend |
| R28.5 | Node styling and legend colors use the existing token palette (`config/layout.js` / app.css) — no new color system | ✅ 2026-08-11 | `L2_ROLE_COLORS` reuses palette tokens |
| R28.T | Vitest coverage — node-legend entries render (source/target/waypoint); L2 no longer renders FlowKindLegend; L1 legend unchanged | ✅ 2026-08-11 | `components/__tests__/DataFlowLegend.test.jsx` — 7 tests, all green |

## R29 — L1 field-level data flow + upstream/downstream query direction (requirement change 2026-08-12)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R29.1 | L1 shows the queried field's data flow — same field-level semantic as L2 — at cross-script scale: scripts + tables between scripts, no fields | ✅ | R29 (2026-08-12) — implemented v3.3.153 |
| R29.2 | Data flow = fields writing the queried field (upstream) + fields reading it (downstream) — BOTH directions are transitive chains (user ruling 2026-08-12): upstream back to the start, downstream down to the end | ✅ | R29 (2026-08-12) — v3.3.153 |
| R29.3 | No table-level inclusion: scripts/tables that only read or write the queried TABLE are excluded | ✅ | R29 (2026-08-12) — v3.3.153 — e.g. SUP_M for a BNQXYE search |
| R29.4 | Direction is a QUERY PANEL setting — upstream (writing, default) / downstream (reading); no L1 panel control | ✅ | R29 (2026-08-12) — v3.3.153 |
| R29.5 | L2 follows the query direction automatically (zoom-in of L1) | ✅ | R29 (2026-08-12) — v3.3.153 |
| R29.6 | L2 flow-reason source/target anchoring follows the direction (user ruling 2026-08-12): downstream → seed = SOURCE (R19.1 unchanged); upstream → seed = TARGET (sources = the fields writing it) | ✅ | R29 (2026-08-12) — v3.3.153 — mirrors R19.7 |
| R29.7 | J12-11 L1 memory reuse of analysis caches (#193) | ✅ | #193 — 2026-08-24 — `analysis_cache_map` memoized per ws_id in `l1_builder.py`, invalidated by the analysis cache-dir file-set/mtime signature; bounded per-workspace LRU; in-memory only (restart-cleanup automatic). Behavior byte-identical (Jaccard 16/16). |
| R29.8 | Final-L1-graph cache (#252) | ✅ | #252 — 2026-08-24 — `_build_l1_graph` return value memoized in-memory (LRU, keyed on ws_id + script_names + table + field + direction + analysis-cache & matched-script file-set signatures); any signature change (re-index/re-extraction/S4b/script edit) → miss → rebuild. Hit returns a copy, byte-identical to a fresh build (Jaccard 16/16). **Team F fix (2026-08-24): empty-analysis-cache workspaces are never memoized NOR served** — a build on an empty cache runs LIVE extraction (run_full_analysis) whose validity the file-set signature does not capture, so memoizing it masked a would-be M4-B degraded outcome on a later identical call (the `test_l1_degraded_fallback_visible` contract). `_analysis_cache_empty(ws_id)` short-circuits the wrapper; indexed (non-empty-cache) workspaces keep full T2 behavior. Residual edge: a NON-empty cache where some matched scripts still miss (stale/unindexed) runs live for those scripts and IS memoized — accepted approximation. |

## R30 — L2 edge flow-direction display: mid-arrow + structure/flow color split + click-edge flow cone + ROW_FLOW (requirement change, 2026-08-13)

> ✅ Implemented & formal (2026-08-21). Formal requirement + solution rows now live in `requirements_v2.md` §R30 (flow cone R30.1–R30.5, ROW_FLOW R30.11); the v3.3.159/160 additions are tracked here as R30.6–R30.10. Code: flow cone v3.3.157/158 (#222 + recolor #239), mid-arrow + uniform style v3.3.157 (#224/#225), ROW_FLOW v3.3.155 (#226).

| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R30.1 | Two edge classes, two color systems: value flow keeps per-type color; structure (SCHEMA/ALIAS/SUBSET) gets one uniform gray; `TABLE_FLOW` re-categorized out of "structure" (value flow) | ✅ | R30 (2026-08-13) — implemented v3.3.157 (#224/#225 L2 uniform edge style) |
| R30.2 | Mid-point direction arrow on value-flow edges (native `mid-target-arrow-shape`), oriented source → target — not the line end (covered by node labels); structure edges carry no arrow | ✅ | R30 (2026-08-13) — implemented v3.3.157 (#224/#225 mid-point arrow) |
| R30.3 | Click-edge flow cone (two colors), anchored to the edge's own flow direction: before (green #2ECC71) = upstream of the edge; after (blue #2196F3) = downstream of it; the edge is the red #FF3B30 pivot; non-cone edges dim | ✅ | R30 (2026-08-13) — implemented v3.3.157/158 (#222 click-edge flow cone, pivot class `flow-cone-pivot`; recolor #239) |
| R30.4 | Value-flow only: structure edges are never part of the cone, never highlighted | ✅ | R30 (2026-08-13) — implemented v3.3.157 (#222) |
| R30.5 | No animation (static one-shot class toggle); L2 only — L1 keeps its static arrows | ✅ | R30 (2026-08-13) — implemented v3.3.157 (#222) |
| R30.6 | Search-after-filter extraction-cache reuse | ✅ | #242 — v3.3.159 — repeated searches after a filter change reuse the extraction cache |
| R30.7 | L2 edge-hover tooltip REMOVED | ✅ | #240 — v3.3.159 (commit a77dfdd) — L2 edge hover tooltip (edge type, counts) removed |
| R30.8 | L2 single-view visibility toggle (View 1 flow-only ↔ View 2 full) | ✅ | #247 — v3.3.160 — in ONE open L2 view, a checkbox toggles between View 1 (only the searched field's flow closure: `flow_node_ids`/`flow_edge_ids`) and View 2 (the full script graph); pure `.show()/.hide()` visibility — positions preserved, never a re-layout. **2026-08-24 (user ruling)**: the toggle label must be English — "Flow only" (the button previously read 仅目标字段流向; UI is English-only, Chinese is allowed solely inside the SQL script content) — see #290 |
| R30.9 | Case1 autocomplete EAST5_SSTZFXXB fix | ✅ | #245 — v3.3.160 — Case1 table autocomplete fixed for EAST5_SSTZFXXB |
| R30.10 | C-H1 L1 cache staleness guard | ✅ | #248 — v3.3.160 — L1 cache staleness guard added |
| R30.11 | ROW_FLOW — the 17th edge type: row-level flow bridge emitted by the L2 walker's R29 continuation (the searched field's row-selection effect into a downstream statement's rows, e.g. subquery output `⟐ t` → CTE `temp_kmbh_gl`) | ✅ | #226 — v3.3.155 — flow-class edge (arrow + highlightable), shares the uniform line style; `ROW_FLOW` in `EDGE_TYPE_STYLE` (#2ECC71 solid width 2) + category "flow" (`backend/app/services/graph_service.py`), documented in `sql_model.py`, emitted by `compute_field_flow`'s continuation rounds (`backend/app/extractor/lineage.py`), rendered "row flow" by `highlight_strategies.py` |

## R31 — Multi-user identity & workspace collaboration (2026-08-19, RELEASED v3.3.162)

> Design note `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`. Released v3.3.162 (task #251). **R31 backend follow-ups (2026-08-24, Team A) — all RESOLVED:** #269 config-provisioned users only (admin endpoint removed), #270 bare `DELETE /api/workspace` removed, #272 L2 layout persistence + creator-only layout editing, #273 heavy-op gate wired in, #279 zero session expiry, #280 same-origin kept (documented), #285 per-user visit logging dropped (+ #278/#281). **R31 frontend follow-ups (2026-08-24, Team B) — all RESOLVED:** #276 shared 401 session-expiry interceptor (E-M1), #277 per-user localStorage namespacing (E-M2), #282 L2 child-delete drops to L1 (E-M7), #283 auto-fit bounds ALL nodes (E-M8), #284 resumeLayouts updated on save (E-M9), #291 L2 READ path applies saved positions, #292 view tree restored on open, #295 workspace management merged into the debugger left panel. #286 (2026-08-24): dashboard folder-upload regression fixed (see R1.2). #293 (2026-08-24): login merged into the debugger left panel (R31.15)

| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R31.1 | **Login entrance page gates every page** of the service; username MUST be `*@hsbc.com` + password (min 6); accounts are **pre-provisioned from CONFIG** (`PROVISIONED_USERS`, unknown usernames rejected — no self-registration); username is an identifier only — **no mail is ever sent** | ✅ | R31 (2026-08-19) — design note `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`; #269 config provisioning (2026-08-24). **SUPERSEDED by #293 (R31.15)** — login no longer gates EVERY page: only the Data Flow Debugger requires login (SQL Analysis is public) |
| R31.2 | **IP audit**: client IP recorded at login and with **every** workspace operation as `{username, ip, ts, action, detail}` — "who modified this" is always answerable | ✅ | R31 (2026-08-19) — **closed v3.3.165 (#316 M-Po4)**: login IP recorded (`auth_service.login` → `last_login_ip`) AND per-operation client IP captured in workspace activity/audit records (no longer `""`) |
| R31.3 | **Share by workspace id**: any logged-in user who knows the id can open/edit; `creator_username` fixed at creation; creator is **alerted in-app** when someone else works on the workspace | ✅ | R31 (2026-08-19) — share-by-id + fixed `creator_username` live (`/workspace/{id}/resume` membership, `create_workspace`); **#285 (2026-08-24): the creator-alert half DROPPED** (per-user visit logging removed) — the share remains |
| R31.4 | **Shared current state, last-writer-wins**: one L1 (the last search) + the opened L2s; resume-by-id shows the current state, never personal history; monotonically increasing `state_version` drives a "state changed by X — refreshed" notice | ✅ | R31 (2026-08-19) — `/workspace/{id}/resume` returns current state; CAS `write_meta_cas` bumps `state_version`, 409 on stale (#272) |
| R31.5 | **Layout persistence (L1 + L2)**: node x/y autosaved **≤1/s** plus a **final write on workspace close**; layout file is **current-state only** (never grows); positions restored on resume, stale ids skipped | ✅ | R31 (2026-08-19) — `PUT /workspace/{id}/layout` (creator-only #272); ≤1/s autosave + final write on close; restore on resume (#284, #291) |
| R31.6 | **"My workspaces" per-user index** (membership = created + visited) with quota `MAX_WORKSPACES_PER_USER` (default 10); at the cap, opening a new workspace requires removing one from the list first | ✅ | R31 (2026-08-19) — `auth_service.add_workspace_to_index` + quota (409 at cap); #295 merged into the debugger left panel |
| R31.7 | **Remove-from-own-history** (any user, index only, never the server copy) vs **physical delete** (creator only — removes the workspace and every user's index entry) | ✅ | R31 (2026-08-19) — `remove_from_my_history` (#270 removed the bare cleanup-all): creator→physical delete + server-global audit first; non-creator→index only |
| R31.8 | **Workspace history readable by any opener**: per-workspace activity log (who, when, IP, what) | ✅ | R31 (2026-08-19) — activity.json NDJSON (O_APPEND) + `GET /workspace/{id}/activity` (any opener) |
| R31.9 | **In-app notifications, one file per user** (`notifications/{username}.json`, kept forever): memo on visit end (close/logout/30-min idle); creator alert if visitor ≠ creator; title `[SQL Data Flow Visualizer] Workspace {ws_id} · {time}` | ✅ | R31 (2026-08-19) — **#285 (2026-08-24): visit-end memos/creator-alerts DROPPED** (per-user visit logging removed). **DELETED by #322 (v3.3.166)** — the notification store + `/api/notifications` endpoints removed entirely (no producers remained post-#285) |
| R31.10 | **Multiple tabs**: visits tracked per (user, workspace); logout/expiry flushes all open visits (one memo each) | ✅ | R31 (2026-08-19) — **#285 (2026-08-24): per-user VISIT LOGGING DROPPED** — the open_visits registry, flush machinery, and visit memos/creator-alerts are removed (E-H6/E-H7/E-M3/E-M6) |
| R31.11 | **Password recovery = admin-mediated reset** (no self-service path overwrites an identity, A-H1); with #269 the ONLY path is re-provisioning from config (`PROVISIONED_USERS`, force-synced at every startup) — no HTTP reset endpoint | ✅ | R31 (2026-08-19) — #269 config provisioning (2026-08-24) |
| R31.12 | **One global heavy-op gate** (debugger search + `/analyze` + `/analyze_multi` + diagnostic `/workspace/{id}/debug/graph`): while one runs, a new one returns HTTP 409 "system busy — please wait" | ✅ | R31 (2026-08-19) — **#273 (2026-08-24) wired in**: `heavy_gate.gate` singleton gates all heavy ops; CPU-bound work moved off the event loop (`asyncio.to_thread`). 2026-08-25: code-review M-P1 wrapped the diagnostic `debug/graph` endpoint in the same gate |
| R31.13 | **Migration**: pre-feature workspaces (no creator) removed directly at rollout; concurrent same-file write loss **accepted** (low concurrency) with atomic temp+rename so files never corrupt | ✅ | R31 (2026-08-19) — `remove_legacy_workspaces()` in the lifespan (no-op once none remain); temp+rename accepted-loss writes (A-M3) |
| R31.14 | **#292 L1/L2 view tree not restored on opening a stored workspace** — the left-panel view tree (search views + their L2 children) is persisted server-side in views.json but the frontend never loads it on open (`listViews` in `frontend/src/api/client.js` is defined but never called; `handleOpenExisting` in `frontend/src/DataFlowApp.jsx` does resume→scan→index and skips views) | ✅ | #292 (2026-08-24) — `handleOpenExisting` calls `api.listViews(wsId)` after index and `setViews(viewsRes.views)`; no auto-activate (R23 clean start) |
| R31.15 | **#293 Login merged into the data flow debugger's left panel** — the full-screen LoginPage gate is removed; the login form lives in the debugger's left panel. ONLY the Data Flow Debugger requires login — SQL Analysis (legacy `/api/analyze`, `/api/analyze_multi`, `/api/scripts`) is public (exempt from the `login_gate` middleware via `PUBLIC_API_PREFIXES` in `backend/app/main.py`). Caveat: `DELETE /api/scripts` (clears the analysis cache) also becomes public — accepted for an internal tool | ✅ | #293 (2026-08-24) — shipped v3.3.164; login form in the debugger left panel, SQL Analysis public |
| R31.16 | **#269 Config-provisioned users only** — the gate-exempt `POST /api/admin/users` bootstrap (E-H1/E-H3) is REMOVED; `/api/admin` is gone from `PUBLIC_API_PREFIXES`. Accounts are provisioned from `config.PROVISIONED_USERS` (default `admin@hsbc.com` / `123456`, env-overridable via `PROVISIONED_USERS_JSON`) at startup — `main.py` lifespan force-syncs every entry. No HTTP endpoint provisions users | ✅ | #269 (2026-08-24) — R31 backend Team A |
| R31.17 | **#270 bare `DELETE /api/workspace` (cleanup-all) removed** (E-H2) — the endpoint and `cleanup_all_workspaces()` are deleted; no session can rmtree every workspace + the notifications dir | ✅ | #270 (2026-08-24) — R31 backend Team A |
| R31.18 | **#272 L2 layout persistence + creator-only layout editing** (E-H4) — the `opened_l2s` prune that silently dropped every `l2:{script}` layout is removed (L2 drag positions now persist; also fixes #291). `PUT .../layout` is now creator-only — a non-creator session gets 403 | ✅ | #272 (2026-08-24) — R31 backend Team A |
| R31.19 | **#273 heavy-op gate wired in** (E-H5) — `heavy_gate.gate` (module singleton) gates debugger search + `/analyze` + `/analyze_multi` + the diagnostic `/workspace/{id}/debug/graph` (M-P1, 2026-08-25); while one runs a new one returns **409 "system busy — please wait"** (released in a finally). CPU-bound work moved off the event loop via `asyncio.to_thread` | ✅ | #273 (2026-08-24) — R31 backend Team A; M-P1 (2026-08-25) wrapped the debug endpoint |
| R31.20 | **#279 ZERO session expiry** (E-M4) — the 30-min absolute `max_age` cookie and the idle-reaper/`last_active` extension are removed. The session cookie has no `max_age` (the browser drops it on close); in-memory sessions live until logout or server restart (A-M9 accepted) | ✅ | #279 (2026-08-24) — R31 backend Team A |
| R31.21 | **#280 Same-origin check kept as defense-in-depth** (E-M5 decision) — NO code change. SameSite=Lax is the real boundary; the origin check stays; the accepted no-Origin / `Origin: null` bypass is documented. The Low CORS `allow_origins=["*"]` item stays out of scope | ✅ | #280 (2026-08-24) — R31 backend Team A (decision recorded) |
| R31.22 | **#285 Per-user visit logging dropped** (E-H6/E-H7/E-M3/E-M6, folds #278/#281) — `visit_service.py` deleted; `open_visits` registry, `open_visit`/`touch_visit`/`flush_session_visits`, visit memos/creator-alerts and all visit `append_activity` calls removed. `close_workspace` is a **no-op returning 200** (frontend `closeWorkspace` kept). Only creator-driven activity events (workspace create/delete/remove-from-history) remain | ✅ | #285 (2026-08-24) — R31 backend Team A |
| R31.23 | **#276 Shared 401 session-expiry interceptor (E-M1)** — `api/client.js` wraps every gated fetch in `gatedFetch`; a 401 from any gated endpoint (not login, not the public analysis endpoints) fires the module-level handler — registered by AppShell on mount via `api.onSessionExpired(cb)` — exactly once per 401 batch, dropping the session (`me=null` → the login form re-renders in the dataflow left panel). No redirect-reload | ✅ | #276 (2026-08-24) — R31 frontend Team B |
| R31.24 | **#277 Per-user localStorage namespacing (E-M2)** — search history/pins keys are now `df_search_history:{username}` / `df_pinned_searches:{username}`; the username flows AppShell → DataFlowApp → FilterPanel. Global keys (theme, the one-time `df_last_search_view` purge) are left untouched; no other per-user `df_*` keys found | ✅ | #277 (2026-08-24) — R31 frontend Team B |
| R31.25 | **#282 Deleting the active L2 child view drops back to L1 (E-M7)** — `handleDeleteView` detects when the deleted view (or its L2 parent) is the active view and clears graphLevel('L1'), l2Result, flowOnly, sqlText, currentScriptName, selectedEdge, l2NotInFlow*/l2ParseErrors, activeViewId | ✅ | #282 (2026-08-24) — R31 frontend Team B |
| R31.26 | **#283 Auto-fit bounds ALL nodes (E-M8)** — `fitAllElements` in `flowVisibility.js` shows every element, calls `cy.fit()` on the full closure, then re-applies flow visibility (preserves D-H2 ordering: fit after the flow-visibility apply) | ✅ | #283 (2026-08-24) — R31 frontend Team B |
| R31.27 | **#284 resumeLayouts updated on layout save (E-M9)** — on layout save success (and 409 fresh-state refresh) `flushLayoutSave` folds the just-saved positions into `resumeLayouts` under the exact `l1` / `l2:{script}` key so re-open applies LATEST positions; `resumeLayoutKey()` (utils/layoutPersistence.js) is the single source of truth for the save/read key | ✅ | #284 (2026-08-24) — R31 frontend Team B |
| R31.28 | **#291 L2 READ path applies saved positions** — L2 open reads `resumeLayouts[resumeLayoutKey('l2', currentScriptName)]` (was mismatched vs the `l2:{script}` save key); together with #272 (backend prune removed) and #284 (frontend resumeLayouts update) L2 drag persistence round-trips | ✅ | #291 (2026-08-24) — R31 frontend Team B |
| R31.29 | **#295 Workspace management merged into the debugger left panel** — the standalone MyWorkspaces dashboard is retired; AppShell always renders `<DataFlowApp>` when logged in; a "My workspaces" section sits at the top of `.panel-left` (list + 📁 Select Folder + zip upload + open-by-id); upload → `api.uploadWorkspace(file)` then `onOpenWorkspace(result.workspace_id)`; WorkspacePanel gets `showUploads={false}` so no second upload picker appears | ✅ | #295 (2026-08-24) — R31 frontend Team B |
| R32.1 | **L2 flow-only-merged view** — over the flow-only closure: every field edge is promoted to its table edge (field endpoint → parent table, never dropped); same-line same-table-pair edges merge into one; edge type removed (single untyped `flow` edge); direction = single arrow (one direction) / double arrow (both directions), never two separate opposite edges; self-loop kept only when it is the line's sole edge, otherwise absorbed; an edge with no SQL-line reference is dropped; a line spanning >2 tables emits one edge per pair. Node set identical to flow-only | ✅ | #329 — SHIPPED v3.3.166 (2026-08-26) |
| R32.2 | **L2 full-merged view** — same merge rule as R32.1 applied over the full graph | ✅ | #329 — SHIPPED v3.3.166 (2026-08-26) |
| R32.3 | **Benchmark for the line-merged views** — canonical merged edges derived independently from SQL (one SQL line ≈ one edge); recall = precision = 1.0 for nodes/edges/highlights | ✅ | #330 — SHIPPED v3.3.166 (2026-08-26) |

## R33 — Dynamic hover label enlargement in L1/L2 graphs (requirement change, 2026-08-27)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R33.1 | Hovering a node enlarges its label + all field chips of its table box | ✅ | `hoverEmphTargets` flat `_tableParent` scan (chips are top-level; `children()` is always empty); `.label-emph` composed LAST in the sheet; v3.3.171/173 |
| R33.2 | Hovering an edge enlarges both endpoint nodes AND their field chips | ✅ | Edge branch returns `connectedNodes()` (was the bare edge — no visible label, invisible no-op; fixed v3.3.176) plus each endpoint's chips via the same `_tableParent` scan (v3.3.177) |
| R33.3 | Per-tier 2× sizing | ✅ | Titles 12→24, field chips 10→20 (`node.label-emph[type="field"]` attribute rule); contract tests pin per-tier minimums |

## R34 — View-open search-params recovery (requirement change, 2026-08-27)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R34.1 | Opening an L1/L2 view from the tree restores table+field into the search panel | ✅ | `recoverViewSearch` (pure) resolves the row or its `parent_view_id` search row; nonce-gated fill so in-flight edits are clobbered only on explicit view open; R23 clean-start on page load untouched; v3.3.178 |
| R34.2 | Never guess | ✅ | Unrecoverable/corrupt rows → `null`, panel left untouched |

## R35 — L2 fit readability: minimal margins + legible zoom floor (requirement change, 2026-08-27)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R35.1 | Fit spends the window on content | ✅ | `FIT_PADDING` 200→60→24; L2 small-panel adaptive 30/7%→16/5% in BOTH the hook and `layoutCore.applyLayout` (the initial-fit path was missed first, synced v3.3.177) |
| R35.2 | Labels legible before hover | ✅ | `minZoom` 0.05→0.28 — at 0.05 a 2× emphasis gained <1 screen px; screen-verified via Playwright class+pixel assertions. **R41 (2026-08-28, FIXED in the pending v3.3.191+ batch)**: the 0.28 floor itself blocked overview zoom — re-lowered to 0.08 with `min-zoomed-font-size` 6 hiding sub-legible labels (the legibility job moved OFF the zoom clamp ONTO the font gate) — see R41.2 |

## R36 — Release pipeline ships the current frontend (build hygiene, 2026-08-27)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R36.1 | `release.sh` rebuilds frontend and syncs `dist → backend/app/static` before docker build | ✅ | Stage 0.5: npm build, stamp VERSION into dist/index.html, sync elk.bundled.js, `git add backend/app/static`. Root cause: the image serves PREBUILT static — v3.3.171–173 shipped v3.3.170's bundle while /api/health reported new versions |
| R36.2 | Deployment truth-test = artifact hash parity, not commit history | ✅ | v3.3.177 race (build predated the recovery commit; history looked inclusive) caught by deterministic-build hash diff; v3.3.178 redeployed with local sha256 == deployed sha256 |

## R39 — Merged self-loop filter labels + Flow-line invariants (v3.3.181)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R39.1 | A merged-view SELF-LOOP (a field→table FILTER edge after R32 promotion, e.g. `east5→east5 @L190`) carries a readable label `⟂ <fields> (filtered @L<line>)` computed CLIENT-side from the detailed closure — payload/snapshots/benchmarks untouched | ✅ | v3.3.181 — `selfLoopFilterLabels` + `edge[filterLabel]` style, composed after the uniform `label:''` rule |
| R39.2 | INV-1: every DML line referencing the searched field carries ≥1 closure edge | ✅ | `backend/tests/test_flow_line_invariants.py` — DML carve-out checked both ways (uncovered DML line OR newly-covered DDL line → red) |
| R39.3 | INV-2: every closure edge is assigned a SQL line (integer ≥1) | ✅ | same gate |
| R39.4 | DDL `ALTER … ADD PARTITION (P_DT=…)` lines stay OUT of the value-flow closure (metadata-only) — codified as INV-1's documented exception, drift fails loudly | ✅ (superseded by R43, 2026-08-28) | EAST5 L166–175 verified excluded; L41/L190 covered. R43 strengthens this from a closure-semantics exception to a GRAPH-level drop: the partition-DDL statement frames are removed from the L2 graph entirely (folder names, not dataflow); the invariant's second side is now the R43 regression guard |

## R37 — L2 node click scrolls the SQL panel to the node's definition line (requirement change, 2026-08-27)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R37.1 | Tapping an L2 node scrolls + highlights the SQL line where that node is defined | ✅ | Node `data.line_start` (the same source that renders the `@L…` suffix) feeds the SINGLE existing `sqlHighlightLine` channel — node and edge clicks share it, last click wins; `SqlPanel.scrollToLine` unchanged (the edge path already proved the channel) |
| R37.2 | Line semantics follow the server contract | ✅ | `intermediate_table` (⟐ output VT) → its statement's anchor line (INSERT/ALTER); physical `source_table` → first occurrence (keeper-by-construction, R22); `alias_table`/`cte` → their FROM/JOIN/WITH line. The tapped element's OWN payload is read — never a label lookup (merged/dedup'd nodes each keep their own `line_start`) |
| R37.3 | Guards | ✅ | Scroll only when `line_start` is an integer ≥ 1 — else silent no-op (TVF alias `f` anchors L0, ledger M-T1: no-ops until fixed, never guesses). First line only (statement spans would need new node payloads — deferred). L2 only (L1 cross-script SQL is different machinery). Node click clears any stale edge reason-panel selection |
| R37.4 | Every table node's line number audited against the sample SQL | ✅ | EAST5 full view: all 25 table nodes checked (physical → line mentions the table; ⟐ VT → statement anchor keyword; alias → FROM/JOIN + alias token). Result: 24/25 exact; 1 known gap = TVF alias `f` at L0 (M-T1, pre-existing) — see audit table in the v3.3.179 commit message |
| R37.5 | **K4 ruling 1 — the ⟐ VT anchor is the CREATION line** (contract AMENDED; the code was already right): a top-level ⟐ output VT anchors on the statement's OWN first token — never the `WITH` line; a nested subquery/derived/EXISTS ⟐ VT anchors on the body's first output line (falling back to the body's SELECT head) | ✅ | 2026-08-28 (K4) — amendment only, no code change; R37.2's "statement anchor line" wording is now precise. Recorded as a design decision in the "K4 rulings" section below |
| R37.6 | **F-B1 (2026-08-29, in flight) — click-to-SQL channel completeness**: field chips carry `line_start` (never `line_end`) from the served payload, the not-in-flow banner text states WHY nothing highlighted, and the direction default flip lands with it | ⏳ | IN FLIGHT — Team F-B1 also owns the CLAUDE.md #23/#28/#29 amendments (parse-errors honesty wording, the R37 line-semantics contract, the direction API closure); those land in CLAUDE.md, not here. Until it lands, a chip click can fall back to the table anchor instead of the chip's own definition line |

## R40 — L2 readability batch (2026-08-27/28, shipped v3.3.187–v3.3.190)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R40.1 | **Filter loop-line anchored to the table border** — the merged-view self-loop's synthetic red loop-line was a detached floating bar ("a red line separately on the screen") | ✅ | v3.3.187 — the anchors parked at `sp.x - off` (no visual tie to anything); they now bracket the table's LEFT BORDER: `x = box.x1 - gap`, y spanning the node's vertical center clamped to the box height — model-space anchor, so it never drifts on pan/zoom between upserts (`flowVisibility.js` upsert over the v3.3.186 `capA_/capB_/capL_<edgeId>` chrome). v3.3.190 diagnostic ruling B1: gap clamped to ~2px so the bracket visibly TOUCHES the border (a 12px screen gap reads as detached) |
| R40.2 | **Caption font zoom-compensated** — the `⟂ <fields> (filtered @L…)` caption stays readable at any zoom | ✅ | v3.3.190 — `'font-size': 'data(caption_font)'` computed per-zoom by `upsertFilterCaptions` (14 model px rendered ~4px at the zoom floor — unreadable); effective on-screen size floors at ~11px |
| R40.3 | **Field Story step-through bar** — the searched field's L2 closure re-told as an ordered story: birth → written → read → filtered → consumed | ✅ | v3.3.188 — `utils/fieldStory.js` (PURE projection of the served payload — no React/cytoscape/SQL text, nothing guessed, no sample text hardcoded) + `components/FieldStoryBar.jsx` (presentational: numbered step chips, ◀/▶, autoplay 3s, ✕ dismiss; ALL state lives in DataFlowApp). Seed = case-insensitive field-node match on the physical-table compound (#288 case folding); only closure edges with a valid `highlight_line` (INV-2) participate, malformed edges skipped never repaired; FIRST-MATCH-WINS classification (birth outranks read — the seed's binding edge is read-shaped but sits at the table's anchor line); steps group per (kind, line), ordered kind-first / line-ascending. Merged+detailed edge-id NAMESPACES: the default view's ids are content-derived `l2m_*`, DISJOINT from the detailed closure's `l2e_*` — each step carries `edgeIds` AND `mergedEdgeIds` (resolved against `full_merged` by (highlight_line, unordered parent-promoted endpoint pair), line-match fallback) or story emphasis silently no-ops in the default view. Dimming `story-dim` 0.15 (the cone-dim convention) on every element the step does not involve. Step-through REUSES the R37 `sqlHighlightLine` channel (scroll + highlight; last wins; `SqlPanel` unchanged). Red-team rulings A1–A10 folded (A1 = the namespace split; exempt chrome never dimmed, never class-tagged) |
| R40.4 | **Flow-reason panel REMOVED; FieldStoryBar relocated to its slot below the SQL panel** | ✅ | v3.3.189 (user ruling) — `EdgeReasonPanel` deleted (the R20/R26 reason surfaces are superseded by the story); the FieldStoryBar takes its slot BELOW the SQL panel |
| R40.5 | **The filter story-step lights the loop-line and golds the caption** | ✅ | v3.3.189 — the Filtered step's underlying edge renders ~0px (detailed: field→own-table endpoints coincide; merged: the self-loop is ~7px) — the f648 invisible-edges finding; the step lights the synthetic chrome (`capL_<edgeId>` loop-line + `cap_<edgeId>` caption). GUARD RULE: story-active can only GROW the loop-line — `edge.filter-loopline.story-active` width 9 (> the chrome's 7; the generic `edge.story-active` width 5 would SHRINK it — later rule wins the specificity tie); the caption golds (`#FFD700`, font 13) |
| R40.6 | **Cache headers** — index.html always revalidates; content-hashed assets immutable forever | ✅ | v3.3.190 — `_VersionedStatic` (`backend/app/main.py`): non-`assets/` responses (index.html) `Cache-Control: no-cache` (ETag still gives 304s); `assets/*` `public, max-age=31536000, immutable`. ROOT CAUSE of the recurring "deployed but user sees old UI" reports: with NO Cache-Control browsers applied RFC 7234 heuristic freshness (~10% × age) to index.html and kept serving a WHOLE OLD bundle across deploys. Complements R36 (the static-sync + hash-parity half of that defect class) |
| R40.7 | **History slim (filter-repo)** | ✅ | v3.3.190+ — repo history rewritten: 1.21GiB → ~150MB clone. EVERY existing clone must RE-CLONE (old remotes hold orphaned pre-rewrite history); image pieces re-committed at HEAD with a re-stamped manifest |
| R40.8 | Same-table (self-pair) merged edge renders as a CURVE and clicking it highlights its SQL line | ✅ | 2026-08-28 (pending release) — root cause: the v3.3.185 "segments" enlargement NEVER rendered — `segment-points` is not a property cytoscape 3.34 understands (segments are driven by `segment-weights`/`segment-distances`; the parsed stylesheet silently drops the unknown property) and a self-edge always routes through `findLoopPoints` whatever `curve-style` says. The REAL knob is the loop properties: `control-point-step-size: data(loopstep)` with `flowVisibility.js` sizing each self-edge's `loopstep` from its endpoint box (`halfWidth + SELFLOOP_BULGE 150`); the dead `segp`/segments bracket machinery removed. (a) the same-table edge renders as a real bulged curve; (b) clicking it highlights its SQL line (DOM-verified on the merged self-loop → SQL L190); the Filtered story step grows the curve under the existing width-9 guard (R40.5) |
| R40.9 | Multi-user test matrix | ✅ | 2026-08-28 — 14 scenarios green (creation / read / write / share paths). The ONE open ruling is now CLOSED: **#380 RESOLVED (2026-08-28)** — POST scan + index are creator-only (same rule as layout/filter-config #272; participants get 403) + regression test (`test_scan_and_index_non_creator_rejected_with_403`) |
| R40.10 | **Field Story Joined/Transformed stage** — a 6th stage (user-authorized ≤10): edges of type JOIN/TRANSFORM/COMPUTED/WINDOW/AGGREGATE touching the seed/table are told as their own story step, ordered between Read and Filtered | ✅ | 2026-08-28 (pending release, v3.3.191) — `utils/fieldStory.js`: `KIND_RANK` birth/written/read/**joined**/filtered/consumed, label "Joined/Transformed", `JOINISH_EDGE_TYPES` = {JOIN, TRANSFORM, COMPUTED, WINDOW, AGGREGATE}; SCHEMA/ALIAS/SUBSET stay non-narrative by design. Evidence = the random-10 field audit: 49 previously-unclassified narrative edges (8 COMPUTED + 7 AGGREGATE + 6 WINDOW + 4 TRANSFORM + …) left source-side fields at 1–2 steps; +30 projected steps across 7/10 fields. Tests extended (`fieldStory.test.js`) |
| R40.11 | **F-B2 (2026-08-29, user-scenario simulation findings) — frontend click/UX hardening**: a field chip's decoration can no longer leak onto its table box, the not-in-flow banner reads as a sentence rather than a bare flag, autocomplete no longer swallows the click aimed at the neighbouring input, and clicking a node with no valid line gives visible feedback instead of a silent no-op | ✅ | 2026-08-29 (pending release) — Team F-B2. Chip-decoration guard (`utils/labelDecoration.js` + `labelDecoration.test.js`), suggestion-dropdown auto-close once the typed name RESOLVES (`FilterPanel.jsx`, the F-B2 finding that the absolutely-positioned dropdown ate the Field-input click), zero-line click feedback, and the banner/autocomplete wording. Fit was re-verified as FIXED in the real UI (R41.1's `recenter:false` + the 0.08 floor), not only in unit tests |
| R40.12 | **Field Story Reappears stage (7th)** — the field occurring again on a line its chip doesn't show (a group/join/partition/predicate occurrence) is told as its own step, ordered between Read and Joined/Transformed; label "Reappears" (deliberately NOT the clause name — 4 of the 9 audited lines are not GROUP BY) | ✅ | 2026-08-30 (audit adjudicated; ships v3.3.193) — `utils/fieldStory.js`: `KIND_RANK` birth/written/read/**reappears**/joined/filtered/consumed. STRICT admission, all four conditions (audit-measured, AD-quality): `edge_type === 'SCHEMA'` AND `source` = the searched table's compound AND `target` = the seed chip AND a valid `highlight_line` (INV-2) ≠ the chip's own `line_start`. The same field instance rides ⟐output/alias/CTE compounds and those emit their own SCHEMA edges INTO the seed chip (1–4 per real closure) — strict own-table-only keeps them out; so does the chip's own line (birth/read already tell it). `buildStep`/`mergedEdgeIds` unchanged and verified generic: 4 of the 9 reappears lines carry a real merged self-loop on the table (`l2m_c06160e84e2a`@246, `l2m_6cc57b037902`@59, `l2m_bebd245bc967`@277, `l2m_95f839718c7e`@529) and ride the step; a foreign pair at the same line never does. Evidence: 9/9 examples gain exactly the audited step (product PL@246, lending_ref SUP_M@59, busi_no RFN@277, repay_acct_no RFN@1413, X5GMAB RFN@489, acnw DL@64, lrr_key PL@247, product DL@529, acnw PL@21); negatives hold — the chip's own line, the foreign-sourced twins, and dm_flag2 RFN keeps exactly written-768/written-1168/consumed×2 (its L1119 mask line reaches the chip from an ⟐output compound). +8 tests in `fieldStory.test.js` (4 audit cases + 4 over real served payload projections), 308 frontend tests green |

## R41 — L2 overview zoom + Fit correctness (2026-08-28 — FIXED in the pending v3.3.191+ release batch)

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R41.1 | Clicking Fit in L2 displays the WHOLE graph | ✅ | 2026-08-28 (pending release) — twin cause confirmed, both halves fixed: (a) `minZoom` 0.28 → **0.08**; (b) user-initiated Fit passes `recenter: false` through `fitAllElements` so `centerOnSeed` no longer re-centers on the seed AFTER the Fit (view-mode toggles keep the default recenter). Audit numbers: the fit wanted 0.08–0.09 while the 0.28 floor clamped it — **87/129 nodes hidden**; floor-lift probe: **129/129 visible** |
| R41.2 | Overview zoom reachable; labels degrade gracefully instead of smearing | ✅ | 2026-08-28 (pending release) — zoom floor 0.08 + `min-zoomed-font-size: 6` (`graphStyles.js`): below legibility labels HIDE instead of smearing — a boxes-only overview (user ruling). Amends R35.2: the legibility job moves OFF the zoom clamp ONTO the font gate |

## R42 — L2 initial layout LEFT→RIGHT (requirement change, 2026-08-28)

User requirement: "L2 initial layout should be from LEFT to RIGHT (tables only; fields kept as
previous arrangement) because our screen is landscape."

Decision: the L2 INITIAL layout is the ELK pipeline (layered, `ELK_DIRECTION='RIGHT'` — the
pre-existing constant in `config/layout.js`, unchanged). The snake layout stays available as a
MANUAL option via the toolbar toggle (the L2 toolbar now carries the same Snake/Pipeline buttons
L1 always had — previously only the L1 toolbar could switch the shared mode). L1's default is
UNCHANGED (snake): the single shared `layoutMode` state is split per level, so flipping the L2
default cannot move L1. Fields are untouched by construction — every layout algorithm positions
tables only and `layoutCore.applyLayout()` derives field positions from `table.pos + frozen
relative offsets` (the single field-positioning site, shared with drag), so the previous field
arrangement is preserved under any table layout.

| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R42.1 | L2 initial layout is left-to-right (landscape screens): sources on the left, DML targets on the right | ✅ | `DataFlowApp.jsx` — L2 `layoutMode` default flipped to `'pipeline'` (per-level state `l2LayoutMode`); ELK layered `RIGHT` was already the pipeline direction (`config/layout.js ELK_DIRECTION`, untouched). Verified headless: EAST5-style 4-layer probe — table x-coordinates form ≥3 strictly ascending layers (`utils/__tests__/ltrLayout.test.js`) |
| R42.2 | Fields keep the previous arrangement | ✅ | No field math changed — `computeFieldRelPos()` frozen offsets + `applyLayout()`/`positionTableFields()` are the single field-positioning site; layout algorithms only emit table coordinates |
| R42.3 | Snake stays a manual option; L1 default unchanged | ✅ | `l1LayoutMode` (default `'snake'`) and `l2LayoutMode` (default `'pipeline'`) are separate states; the L2 `DataFlowGraph` now receives `onToggleLayout` (the prop already existed) so Snake/Pipeline switch in the L2 toolbar too |
| R42.4 | **M-E1**: merged vs detailed L2 views share one layout-persistence key — a drag in one view pinned positions in the other | ✅ | Split by view family: merged views (`flow-merged`/`full-merged`) persist under `l2:merged:{script}`, detailed views keep `l2:{script}`. Implemented at BOTH the save path (`scheduleLayoutSave` script key) and the read path (`savedPositions`) in `DataFlowApp.jsx`; `layoutPersistence.resumeLayoutKey` unchanged (`resumeLayoutKey('l2','merged:X') → 'l2:merged:X'` composes exactly); backend unchanged — `save_layout` treats the script value as a free-form key (`f"l2:{script}"`, no script-name validation) |
| R42.5 | Wide graphs on small L2 panels stay usable | ✅ (by fit) | ELK RIGHT spreads horizontally; the initial fit + adaptive padding (R35) keep the whole graph in view, and the in-flight R41 fit-floor work makes overview fit fully correct. Rollback = flip `l2LayoutMode` default back to `'snake'` (one line) |

## R43 — Partition-DDL statement frames dropped from the L2 graph (user ruling, 2026-08-28, task #384)

User ruling: "ALTER TABLE ADD PARTITION statements should not appear in the L2 graph — they are
folder names, not dataflow." A partition ADD/DROP/MSCK statement creates a metadata slot on a
table and moves no values; rendering its statement frame — a ⟐ output VT per ALTER plus two
structure edges (the read-leg TABLE_FLOW into the VT and the REF back to the table) — was pure
display noise on the data-flow picture (EAST5 carried ten such frames @L166–175).

Decision: drop the pure-metadata DDL statement frames from the L2 graph ENTIRELY — full AND flow
views. Implementation is DISPLAY-LAYER ONLY: `_drop_partition_ddl_frames` in
`backend/app/services/l2_builder.py`, applied immediately after the graph-cache load and BEFORE
the relevance filter, so every downstream phase (closure walk, DML trunk routing, payload,
merged views) consumes the clean graph.

- **Detection (conservative)**: a statement-level output VT (`label == "⟐ output"`,
  `variable_type == virtual_table`, context `TOP{n}`) whose statement text — the SQL lines from
  the node's own `line_start` through the statement-terminating `;` — matches
  `ALTER TABLE … (ADD|DROP|MSCK) … PARTITION`. Column DDL (`ADD COLUMN`), CREATE TABLE/CTAS (a
  real dataflow target) and SET (already produces no VT) are out of scope — no evidence they
  frame anything but real structure.
- **Extraction untouched**: no `EXTRACTOR_VERSION` bump; TOPn statement indexing unchanged
  (benchmark pins like EAST5's rrcdm-INSERT `TOP11` stay valid).
- **Cache**: NO `GRAPH_CACHE_PREFIX` bump — the suppression is a deterministic post-load
  projection applied on EVERY consumption path, so caches written before R43 (which still
  contain the frames — probe-verified: a pre-change graph cache serves the identical post-R43
  display) remain valid. The cache stays extraction truth; the display is a projection of it.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R43.1 | ALTER TABLE … ADD/DROP/MSCK PARTITION statement frames (the ⟐ output VTs + their structure edges) never appear in the L2 graph — full AND flow views | ✅ | EAST5 full L2: 129 → 119 nodes, 168 → 148 edges (the ten `output` VTs @L166–175 + their 20 edges gone; zero nodes with `line_start` in 166–175 and zero edges anchored there after). Flow closure `east5_stzfxxb.p_dt` UNCHANGED (5 nodes / 7 edges, `search_matched` true — no closure edge ever anchored on an ALTER line) |
| R43.2 | Extraction / TOPn indexing unchanged | ✅ | `EXTRACTOR_VERSION` untouched (2026-08-26.1); `tests/test_jaccard_benchmark.py` all floors green incl. the EAST5 `TOP11` write-leg pin (22 passed with the invariants suite) |
| R43.3 | INV-1 simplification | ✅ | The "DDL ADD PARTITION lines are the documented exception" carve-out is MOOT — R39.4 superseded: the frames are dropped from the GRAPH, not merely excluded from a closure that still displays them. `test_inv1_every_dml_field_line_has_an_edge_and_ddl_stays_excluded` keeps the two-sided assert — DML lines covered AND no closure edge on a partition-DDL line (the second side is now the R43 regression guard) |
| R43.4 | Costs | ⏳ | Snapshot regeneration PENDING — `tests/test_l2_snapshot.py` (l2_snapshot_02 pins pre-R43 EAST5 full-graph counts) is EXPECTED TO FAIL until the orchestrator's unified regeneration (a parallel team owns the snapshots right now; not rebaselined here). `total_nodes` in the level2 response drops by the dropped raw nodes on the full view (display-only; no consumer pins it). **2026-08-29 note:** the red set is EXPECTED TO GROW (≈46 → ≈75 snapshots) until the unified rebaseline runs — drivers: R44's occurrence twins (incl. R45 family 3), the F-B1 chip `line_start` keys, the K3 sample repairs, the filter-operand twins (R44.4) — see the DRAFT/PENDING entry in `SNAPSHOT_CHANGELOG.md`. Snapshot failures before that point are expected rebaselines, NOT regressions |

## R44 — Walker occurrence coverage (user ruling, 2026-08-28) — ✅ LANDED (pending release; R45 family 3 included)

User ruling: **"flow-only must cover ALL occurrences"** of the searched field — the flow-only
closure's purpose is every dataflow-relevant occurrence, not a first-hit walk. A 30-case audit
measured **~50% occurrence coverage**; 17 walker misses fall into 5 classes: constant writes,
rename-writes, predicates/window keys, derived passthrough, cross-statement asymmetry.

Implementation landed in the working tree 2026-08-28 (tasks #385–#387), stamped
`EXTRACTOR_VERSION 2026-08-28.3 → 2026-08-28.7` (see the changelog comment at the top of
`backend/app/extractor/variable_extractor_v2.py`):

- **Families 1/2 — write-side + derived-read twins** (`_register_flow_occurrence_twins`): a DML
  statement's output projection materializes an occurrence-side `{target}.{col}` twin attributed
  to the write target (source_columns deliberately EMPTY — the twin is the write slot, not a
  read), and a read through a single-physical-source derived alias materializes `{P}.{col}` on
  the physical owner. L-E4 folded into the same version bump (one cache invalidation).
- **GROUP BY occurrence twins** (`_register_groupby_twins`): every GROUP BY item column with a
  resolved physical owner registers a twin anchored on the item's own line (clause-keyword token
  run) — PL L246/247-style group-key lines now anchor.
- **WINDOW anchors move to the OVER line** (`highlight_strategies._anchor_line`): the edge rides
  the window application's own line instead of the window var's `line_start`, so window-key lines
  are reachable in flow-only closures (review finding M14).
- **l2_builder write-target parenting** (#387 follow-up): when the SEARCH targets the write
  table, a derived-alias write projection attributed to a real read source re-parents onto the
  write target — display projection only, extraction untouched.
- **R45 / family 3 — occurrence-line twins** (`_collapsed_occurrences` + family 3 of
  `_register_flow_occurrence_twins`): `_add`'s (name, type, context) dedup keeps ONE node per
  field per scope, so the 2nd..Nth occurrence of a field inside the same statement left NO node
  at its own line. Concrete shapes fixed: a CASE's 2nd WHEN arm (RFN L439), an NVL fallback
  operand (RFN L1029/L1314), a byte-identical repeated projection (RFN L525), the second leg of a
  multi-line JOIN ON predicate (PL L250), an ELSE arm (EAST5 L52). Purely additive — no existing
  var's line moves.
- **2026-08-28.5** (deferred-findings M1/M3): write-side twins admit `VariableType.LITERAL`
  (constant projections now materialize), and the bare-INSERT merge also merges a following
  `Union`/`Intersect`/`Except` (a `SELECT … UNION ALL SELECT …` write source no longer severs).
- **2026-08-28.7** (K4 ruling 3): the structural paren-balance check (`_paren_balance_errors`) —
  diagnostics only, no extraction semantics change; bumps the version so caches written by .6
  with `parse_errors: []` are invalidated.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R44.1 | The flow-only closure covers every dataflow-relevant occurrence of the searched field (all 5 miss classes) | ✅ | 2026-08-28 (pending release) — all five families above landed (`variable_extractor_v2.py` + `dependency_graph.py` Phase 4d-gb + `highlight_strategies.py` + `l2_builder.py`). Verification caveat: the 30-case occurrence audit has not been RE-RUN against the landed walker — R44.2's re-derived benchmark is the gate that closes it |
| R44.2 | Benchmark re-derivation follows the new walker | ⏳ | ground truth is re-derived independently (never from the system's own output); the gate stays set-equality (recall AND precision both 1.0), not a size check. IN FLIGHT: the PL stray-`;` repair (R13.7) moves 3 canonical rows and those are being re-pinned |
| R44.3 | Unified snapshot regeneration lands with R44 | ⏳ | all L2 snapshots regenerate once at the next release (R43 DDL-drop + RFN #370 + R44 twins + the chip `line_start` keys + the K3 sample repairs together) — see R43.4 and the DRAFT entry in `SNAPSHOT_CHANGELOG.md`; snapshot failures before then are expected, not regressions |
| R44.4 | **Filter-operand twin edges (F-E1, 2026-08-29 simulation finding)** — the seed's occurrence inside a filter's operand expression carries its own edge, so the operand line is reachable and the merged view can anchor it | ⏳ | IN FLIGHT — Team F-E1. Same occurrence-twin mechanism as family 3, extended to filter operands (e.g. the `NOT IN` / `CONCAT(...)` operand sides of a seed comparison) |

## K4 rulings (2026-08-28) — contract amendments, recorded as design decisions

Four rulings from the K4 walkthrough. Two amend a documented contract (the code was already
right — the DOC moved, not the code), one is a new diagnostics gate, one closes the direction
API. None of them changes extraction semantics.

| ID | Ruling | Status | Trace |
|----|--------|--------|-------|
| K4.1 | **The ⟐ VT anchor is the creation line.** Top-level ⟐ output VT: the statement's OWN first token — never the `WITH` line (a CTE-bearing statement's anchor is the DML/SELECT keyword, so a click lands on the statement that produces the output, not on the clause that names an intermediate). Nested subquery/derived/EXISTS ⟐ VT: the body's first output line, falling back to the body's SELECT head | ✅ | R37.2/R37.5 amended; code unchanged (verified right) |
| K4.2 | **`parse_errors` honesty via a structural paren-balance check** — `ErrorLevel.IGNORE` recovers a partial tree from almost anything, so a statement whose parens never close parsed into a plausible graph with a clean `parse_errors: []`. `_paren_balance_errors` now runs ONE tokenizer pass over the ORIGINAL script (string/comment aware), splits at `;` TOKENS and records every statement still holding `(` open at its end | ✅ | `EXTRACTOR_VERSION 2026-08-28.7` — diagnostics ONLY (no node/line/edge moves); extraction never rejects, the detail says the recovered tree may be incomplete. CLAUDE.md decision #23 |
| K4.3 | **`direction` is accepted but NEVER honored** — every search and every L2 fetch runs downstream; an omitted value AND a legacy `"upstream"` coerce to `"downstream"` at the router boundary (`_normalize_direction`); only values outside {upstream, downstream} return 400. One direction, one mental model: "where does this field's value go" | ✅ | amends R29.4/R4.13 (R38, v3.3.180). The upstream walker machinery below the router is untouched (API-unreachable); retirement is a future work item. CLAUDE.md decision #29 |
| K4.4 | **Never guess a line: a node with no valid `line_start` (integer ≥ 1) no-ops the SQL highlight** — visible feedback instead of a silent scroll-to-top (F-B2 landed the feedback; F-B1 lands the chip `line_start` payload) | ✅ / ⏳ | R37.3/R37.6 — the guard is shipped, the chip payload half is F-B1's in-flight work |

## User-scenario simulation (2026-08-29) — 50 seeded targets, 4 teams

A seeded end-to-end walkthrough of 50 realistic user targets (table.field searches across the
four sample workspaces) run by four parallel teams (F-A backend search, F-B1/F-B2 frontend,
F-C extraction, F-E1 walker). Headline result: **the click → SQL-highlight channel is exact** —
30/30 browser PASS, and **0 parser-span violations across 16,129 edges / 7,745 nodes** (no
highlighted span ever contradicts the SQL it claims to anchor).

| Finding | Verdict | Trace |
|---------|---------|-------|
| Backend search was case-SENSITIVE while the frontend resolved case-insensitively — disjoint case-variant script sets (TEMP_RFN vs temp_rfn) made a correct search return `no_matches` | ✅ FIXED (F-A) | R2.11 (`resolve_name_ci` / `scripts_for_name_ci`) |
| RFN rate-lookup block carried 2 missing closing parens; PL L19 carried a stray `;` splitting a statement | ✅ FIXED (K3, pixel evidence) | R13.7 (jaccard re-pin in flight → R44.2) |
| Family-3 occurrence twins: the 2nd..Nth occurrence of a field inside one statement had no node at its own line | ✅ FIXED (F-C, R45) | R44.1 (2026-08-28.6) |
| Chip-decoration leak, dropdown eating the neighbouring input's click, silent zero-line click, banner wording; Fit re-verified in the real UI | ✅ FIXED (F-B2) | R40.11 |
| Field chips carry `line_start`; banner text; direction default flip | ⏳ IN FLIGHT (F-B1) | R37.6 |
| Filter-operand occurrences lack their own twin edge | ⏳ IN FLIGHT (F-E1) | R44.4 |

## Code-review decisions (2026-08-25) — SHIPPED v3.3.165

One-by-one walkthrough of `wiki/CODE_REVIEW_2026-08-24.md`. Decisions recorded; the GO came and the
whole batch shipped in v3.3.165 (commit `7e67f0e`, "code-review security hardening + notification
removal + layout fixes"). See the `requirements_v2.md` "Code-review decisions" amendment for the
full design. 2026-08-28: the 11 `⏸` rows below were flipped to ✅ against verified code — they had
contradicted the ✅ requirement rows (R31.2/R31.9/R1.8) since v3.3.165.

| ID | Decision | Status | Trace |
|----|----------|--------|-------|
| M-Po3 | REQUIRE_LOGIN fails **closed** — `config.py:29` default flips ON; test suite authenticates as `admin@hsbc.com` | ✅ | #315 — shipped v3.3.165 (`config.py` default `"true"`; `test_r31_gate.py` subprocess-verifies) |
| M-Po4 | Per-operation client IP in activity/audit (completes R31.2) | ✅ | #316 — shipped v3.3.165 (see R31.2 ✅ row) |
| M-Po5 | Access model: reads open to all authenticated users; creator-only on user-level mutations (filter/export-config, views) | ✅ | #317 — shipped v3.3.165 (`workspace.py` creator checks on layout/filter/export/reset + view children) |
| M-Po6 | `audit.json`/`activity.json` created `0600` (owner-only) | ✅ | #318 — shipped v3.3.165 (`audit_service.py:37` `os.open(..., 0o600)`, `users.json` tmp `chmod(0o600)`) |
| M-Po7 | Session revocation on password change (zero-expiry kept, #279) | ✅ | #319 — shipped v3.3.165 (`revoke_user_sessions` on provision force-sync) |
| M-S1 (D-M1) | Search scope = physical tables/fields only — folder_index Fix A curation (R1.8) | ✅ | #308 — shipped v3.3.165 (see R1.8 ✅ row) |
| M-L1 | L1 drags saved under their own level key (not the L2 key when L2 is open) | ✅ | #309 — shipped v3.3.165 (explicit level key on `handlePositionsChange`; `resumeLayoutKey('l1'/'l2:{script}')`) |
| M-L2 | Flow-only ↔ full toggle is pure visibility — camera-stable, never re-layout | ✅ | #310 — shipped v3.3.165 (`flowVisibility.js` `.show()`/`.hide()` only; still enforced by `test_flow_line_invariants.py`) |
| H1 | Login throttling — exponential backoff, per-username + per-IP, no lockout | ✅ | #303 — shipped v3.3.165 (`auth_service.record_failed_login` backoff; residual M-A1 cardinality cap remains open) |
| #322 | R31 notification subsystem removed (no producers remain post-#285) | ✅ | #322 — shipped v3.3.165 (see R31.9 ✅ row; no `/api/notifications` route remains) |
| #320 | Low hardening backlog — 28 items, 2 covered (mark_read moot / empty-IP = M-Po4) | ✅ | #320 — shipped v3.3.165 (guards landed in folder_index, l1_builder, multi_script_service, workspace_service, audit_service, auth_service — commit `7e67f0e`) |

## Summary
| Metric | Count |
|--------|-------|
| ✅ Implemented | 196 — 2026-08-29 additions: R44.1 flipped ⏳ → ✅ (occurrence coverage landed), NEW R2.11 (backend CI search, F5-extension), R5.13 (#386 CTE-scope ruling), R13.7 (simulation sample repairs, re-pin pending), R37.5 (K4 VT-anchor amendment), R40.11 (F-B2 UX hardening). 2026-08-28 additions (pending-release batch): R40.8, R41.1/R41.2, R2.9/R2.10 (F2/F5, audit #383), R5.12 (MERGE-target fold, #386), R13.6 (RFN OCR recovery #370), R40.10 (Joined/Transformed stage); prior composition: 90 R1–R16 + 17 R17–R20 + 16 R26–R28 + 8 R29 + 11 R30 + R5.10/R5.11 (#288/#289) + 29 R31 + 3 R32 + 11 R40 (R40.1–R40.11) + 2 R41 (R41.1/R41.2) |
| 📝 Partial — in progress | 0 — none (R31.2 IP audit + R1.8 search scope both closed v3.3.165) |
| ⏳ In flight | 5 rows — R43.4 + R44.2/R44.3 (benchmark re-pin + unified snapshot regeneration), R44.4 (filter-operand twin edges, F-E1), R37.6 (F-B1 chip `line_start` + banner + direction flip) |
| ✅ Code-review decisions batch (2026-08-25) | 11 tasks — #303, #308–#310, #315–#320, #322 — ALL SHIPPED v3.3.165 (commit `7e67f0e`); the "Code-review decisions" table rows were flipped ⏸ → ✅ 2026-08-28 |
| ✅ Code review 2026-08-28 | 31 first-pass findings FULLY ADJUDICATED 2026-08-29 — 23 fixed, 6 false positives, 2 deferrals (verdict table: `wiki/CODE_REVIEW_2026-08-28.md` §"Resolution status (2026-08-29)") |
| K4 rulings | 4 recorded 2026-08-28 as design decisions (see the "K4 rulings" section) |
| Version | 3.3.190 (v3.3.191+ batch staged in the working tree, pending release) |

## Key Fixes since V3.2.1
| Fix | Description |
|-----|-------------|
| Category mapping | _get_category() now returns 7 categories (copy/compute/aggregate/filter/combine/write/structure) instead of edge_type directly |
| Compound table styles | Added source_table, intermediate_table, output_table styles for L2 compound nodes |
| Operation badges | Script nodes show abbreviated role badges (R/J/F/A/W/T/C...) in label |
| Category legend | Added 7-category CATEGORY_LEGEND for L2 views |
| Test coverage | 12 new tests in test_category_mapping.py |
| line-style: double | Fixed to solid with dash pattern |
| ELK.js import | Two-tier loading: ESM → UMD script tag |
| Autocomplete overlay | Click-away handler prevents blocking |
| Syntax errors | Fixed useEffect placement in DataFlowApp.jsx and DataFlowGraph.jsx |

