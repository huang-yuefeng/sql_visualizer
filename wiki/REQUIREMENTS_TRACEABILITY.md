# Requirements Traceability Matrix — V3.3.164

> Maps all requirements from REQUIREMENTS.md to implementation status.
> Last updated: 2026-08-25 (R31 status markers reconciled with shipped code — 8 previously-📝 rows flipped to ✅ against verified implementation; summary recounted: 169 implemented / 1 partial (R31.2 IP audit, pending M-Po4); version bumped to 3.3.164. Prior 2026-08-24: #288/#289 L2 graph backend fixes — case-insensitive physical-table merge shipped; #289 INSERT write-column routing corrected to be a model-following fallback (write columns land on their physical-model owner; only phantom-sourced columns land on the write target); #286 R31 regression fixed — dashboard folder upload restored; R31 status → released v3.3.162, E-series review fixes pending)

## Legend
- ✅ Implemented & verified
- ❌ Not yet implemented

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
| R1.8 | Search scope = real physical tables/fields only | 📝 | 2026-08-25 ruling — physical columns already indexed; derived/computed aliases still leak via the Fix A `source_tables[0]` fallback (D-M1, `folder_index_service.py:646-650`) → pending #308 (folder_index curation) |

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
| R4.13 | Direction = query panel setting (upstream = writing, default / downstream = reading); L1 renders the flow in that direction; no L1 panel control | ✅ | R29 (2026-08-12) — v3.3.153 |

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
| R5.9 | L2 follows the query direction automatically — zoom-in of L1's directional flow, no separate control | ✅ | R29 (2026-08-12) — v3.3.153 |
| R5.10 | **#288 L2 physical tables merge CASE-INSENSITIVELY into one compound node** — east5_stzfxxb / EAST5_STZFXXB previously split into 2 nodes | ✅ | #288 (2026-08-24) — Team C backend — the physical-table merge key is case-folded (one keeper, merged-away nids re-point via occ_to_id, edges re-pointed); aliases / CTEs / subqueries stay case-sensitive — a case-twin alias (A vs a) is still a DIFFERENT alias node. Tests: `tests/test_l2_case_merge.py` |
| R5.11 | **#289 INSERT write-alias columns render ON the write target node** — but only as a FALLBACK: a SELECT-projection column sourced to a phantom alias (no real model owner) lands on the write target; a projection sourced to a real table/CTE/alias renders on that source (its physical-model owner), keeping the display a pure projection of the model | ✅ | #289 (2026-08-24, Team C) + Team E correction 2026-08-24 — each statement's ⟐-output SCHEMA members (its SELECT projections) re-parent onto that statement's DML write target's keeper compound ONLY when the projection has no visible source parent; the physical model is the independent truth — write columns sourced to a real table render on that owner, not on the target (nbjgh→bdm_acc_loan_info, internal_key→loan_final, LENDING_REF→ods_ccb_cb_loan_acctloan), while phantom-sourced projections (bz, TAG_*, RESERVED_*, PRIMARY_SRC_SYSTEM) render on the target. DML ⟐-output routing untouched (no qo_ nodes, write legs still hang off each statement's own output VT). Tests: `tests/test_l2_case_merge.py` |

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
| R31.1 | **Login entrance page gates every page** of the service; username MUST be `*@hsbc.com` + password (min 6); accounts are **pre-provisioned from CONFIG** (`PROVISIONED_USERS`, unknown usernames rejected — no self-registration); username is an identifier only — **no mail is ever sent** | ✅ | R31 (2026-08-19) — design note `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`; #269 config provisioning (2026-08-24) |
| R31.2 | **IP audit**: client IP recorded at login and with **every** workspace operation as `{username, ip, ts, action, detail}` — "who modified this" is always answerable | 📝 | R31 (2026-08-19) — **partial**: login IP recorded (`auth_service.login` → `last_login_ip`); per-operation IP is still `""` in workspace-create/remove activity — pending code-review M-Po4 |
| R31.3 | **Share by workspace id**: any logged-in user who knows the id can open/edit; `creator_username` fixed at creation; creator is **alerted in-app** when someone else works on the workspace | ✅ | R31 (2026-08-19) — share-by-id + fixed `creator_username` live (`/workspace/{id}/resume` membership, `create_workspace`); **#285 (2026-08-24): the creator-alert half DROPPED** (per-user visit logging removed) — the share remains |
| R31.4 | **Shared current state, last-writer-wins**: one L1 (the last search) + the opened L2s; resume-by-id shows the current state, never personal history; monotonically increasing `state_version` drives a "state changed by X — refreshed" notice | ✅ | R31 (2026-08-19) — `/workspace/{id}/resume` returns current state; CAS `write_meta_cas` bumps `state_version`, 409 on stale (#272) |
| R31.5 | **Layout persistence (L1 + L2)**: node x/y autosaved **≤1/s** plus a **final write on workspace close**; layout file is **current-state only** (never grows); positions restored on resume, stale ids skipped | ✅ | R31 (2026-08-19) — `PUT /workspace/{id}/layout` (creator-only #272); ≤1/s autosave + final write on close; restore on resume (#284, #291) |
| R31.6 | **"My workspaces" per-user index** (membership = created + visited) with quota `MAX_WORKSPACES_PER_USER` (default 10); at the cap, opening a new workspace requires removing one from the list first | ✅ | R31 (2026-08-19) — `auth_service.add_workspace_to_index` + quota (409 at cap); #295 merged into the debugger left panel |
| R31.7 | **Remove-from-own-history** (any user, index only, never the server copy) vs **physical delete** (creator only — removes the workspace and every user's index entry) | ✅ | R31 (2026-08-19) — `remove_from_my_history` (#270 removed the bare cleanup-all): creator→physical delete + server-global audit first; non-creator→index only |
| R31.8 | **Workspace history readable by any opener**: per-workspace activity log (who, when, IP, what) | ✅ | R31 (2026-08-19) — activity.json NDJSON (O_APPEND) + `GET /workspace/{id}/activity` (any opener) |
| R31.9 | **In-app notifications, one file per user** (`notifications/{username}.json`, kept forever): memo on visit end (close/logout/30-min idle); creator alert if visitor ≠ creator; title `[SQL Data Flow Visualizer] Workspace {ws_id} · {time}` | ✅ | R31 (2026-08-19) — **#285 (2026-08-24): visit-end memos/creator-alerts DROPPED** (per-user visit logging removed); the notification store + endpoints remain for creator-driven events |
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
| R32.1 | **L2 flow-only-merged view** — over the flow-only closure: every field edge is promoted to its table edge (field endpoint → parent table, never dropped); same-line same-table-pair edges merge into one; edge type removed (single untyped `flow` edge); direction = single arrow (one direction) / double arrow (both directions), never two separate opposite edges; self-loop kept only when it is the line's sole edge, otherwise absorbed; an edge with no SQL-line reference is dropped; a line spanning >2 tables emits one edge per pair. Node set identical to flow-only | ⏸ | #329 (2026-08-25) |
| R32.2 | **L2 full-merged view** — same merge rule as R32.1 applied over the full graph | ⏸ | #329 (2026-08-25) |
| R32.3 | **Benchmark for the line-merged views** — canonical merged edges derived independently from SQL (one SQL line ≈ one edge); recall = precision = 1.0 for nodes/edges/highlights | ⏸ | #330 (2026-08-25) |

## Code-review decisions (2026-08-25) — queued, awaiting GO

One-by-one walkthrough of `wiki/CODE_REVIEW_2026-08-24.md`. Decisions recorded; implementation
queued behind the go-command. See the `requirements_v2.md` "Code-review decisions" amendment for
the full design.

| ID | Decision | Status | Trace |
|----|----------|--------|-------|
| M-Po3 | REQUIRE_LOGIN fails **closed** — `config.py:29` default flips ON; test suite authenticates as `admin@hsbc.com` | ⏸ | #315 |
| M-Po4 | Per-operation client IP in activity/audit (completes R31.2) | ⏸ | #316 |
| M-Po5 | Access model: reads open to all authenticated users; creator-only on user-level mutations (filter/export-config, views) | ⏸ | #317 |
| M-Po6 | `audit.json`/`activity.json` created `0600` (owner-only) | ⏸ | #318 |
| M-Po7 | Session revocation on password change (zero-expiry kept, #279) | ⏸ | #319 |
| M-S1 (D-M1) | Search scope = physical tables/fields only — folder_index Fix A curation (R1.8) | ⏸ | #308 |
| M-L1 | L1 drags saved under their own level key (not the L2 key when L2 is open) | ⏸ | #309 |
| M-L2 | Flow-only ↔ full toggle is pure visibility — camera-stable, never re-layout | ⏸ | #310 |
| H1 | Login throttling — exponential backoff, per-username + per-IP, no lockout | ⏸ | #303 |
| #322 | R31 notification subsystem removed (no producers remain post-#285) | ⏸ | #322 |
| #320 | Low hardening backlog — 28 items, 2 covered (mark_read moot / empty-IP = M-Po4) | ⏸ | #320 |

## Summary
| Metric | Count |
|--------|-------|
| ✅ Implemented | 169 (all) — 89 R1–R16 + 17 R17–R20 + 16 R26–R28 + 8 R29 (R29.1–R29.6 + R29.7 #193 + R29.8 #252) + 11 R30 (R30.1–R30.5 flow cone + R30.6–R30.10 v3.3.159/160 amendments + R30.11 ROW_FLOW) — R5.10/R5.11 = #288/#289 (2026-08-24, Team C) + 28 R31 (R31.1–R31.29, recounted 2026-08-25) |
| 📝 Partial — in progress | 2 — R31.2 (IP audit: login IP recorded; per-operation IP capture pending — code review M-Po4) + R1.8 (search scope = physical tables/fields only — 2026-08-25 ruling; derived aliases still leak via Fix A fallback, pending #308) |
| ⏸ Awaiting GO — code-review batch (2026-08-25) | 11 tasks — #303, #308–#310, #315–#320, #322 (see "Code-review decisions" table; requirements_v2.md amendment is the coding reference) |
| Version | 3.3.164 |

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

