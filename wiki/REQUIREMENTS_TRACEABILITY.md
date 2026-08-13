# Requirements Traceability Matrix — V3.3.153

> Maps all requirements from REQUIREMENTS.md to implementation status.
> Last updated: 2026-08-13 (R29 implemented v3.3.153 — R29 rows + derived rows flipped 📝 → ✅)

## Legend
- ✅ Implemented & verified
- ❌ Not yet implemented

---

## R1 — Folder Upload & File Tree (from requirements_v2.md §1)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R1.1 | Upload folder (zip) | ✅ | Upload .zip button works |
| R1.2 | Direct folder upload (no zip) | ✅ | "Select Folder" button uses webkitdirectory + JSZip client-side |
| R1.3 | Hierarchical file tree display | ✅ | FolderTree component in left panel |
| R1.4 | SQL files clickable, non-SQL grayed | ✅ | is_sql flag, non-SQL dimmed and not clickable |
| R1.5 | Multi-select scripts/folders with checkboxes | ✅ | Checkboxes with [deselect all] |
| R1.6 | Multiple users, separate workspaces | ✅ | UUID workspace IDs |
| R1.7 | Extract tables/fields as search indexes | ✅ | tableIndex, fieldIndex from all selected scripts |

## R2 — Filter Panel / Search (from requirements_v2.md §2)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R2.1 | Table name autocomplete | ✅ | Color-coded dots per table |
| R2.2 | Field name autocomplete | ✅ | Table-colored dots from associated table |
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
| R4.5 | Tooltips on edge hover showing type + description | ✅ | Edge tooltip popup for both L1 and L2 |
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
| R28.3 | The L2 edge legend is removed; edge flow-kind midpoint labels (R25 rule 5) and the hover tooltip (edge type, counts — R25 secondary surface) remain | ✅ 2026-08-11 | L2 edge legend gone; midpoint labels + tooltip untouched |
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

## R30 — L2 edge flow-direction display: mid-arrow + structure/flow color split + click-edge flow cone (requirement change, 2026-08-13)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R30.1 | Two edge classes, two color systems: value flow keeps per-type color; structure (SCHEMA/ALIAS/SUBSET) gets one uniform gray; `TABLE_FLOW` re-categorized out of "structure" (value flow) | 📝 | R30 (2026-08-13) — see bug list J12-23 |
| R30.2 | Mid-point direction arrow on value-flow edges (native `mid-target-arrow-shape`), oriented source → target — not the line end (covered by node labels); structure edges carry no arrow | 📝 | R30 (2026-08-13) |
| R30.3 | Click-edge flow cone (two colors), anchored to the edge's own flow direction: before (amber #F5A623) = upstream of the edge; after (cyan #22D3EE) = downstream of it; the edge is the gold pivot; non-cone edges dim | 📝 | R30 (2026-08-13) |
| R30.4 | Value-flow only: structure edges are never part of the cone, never highlighted | 📝 | R30 (2026-08-13) |
| R30.5 | No animation (static one-shot class toggle); L2 only — L1 keeps its static arrows | 📝 | R30 (2026-08-13) |

## Summary
| Metric | Count |
|--------|-------|
| ✅ Implemented | 114 (all) — 83 through R16 + 17 for R17–R20 + 14 for R26–R28 (count corrected to the actual row total, 2026-08-11) |
| 📝 Design, not implemented | 1 — R30 (docs pending) |
| Version | 3.3.153 |

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

