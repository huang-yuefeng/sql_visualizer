# Requirements Traceability Matrix — V3.3.104

> Maps all requirements from REQUIREMENTS.md to implementation status.
> Last updated: 2026-07-30

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

### R18.1 — Empty Table Cleanup
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R18.1.1 | Remove tables with 0 field children | ✅ | v3.3.105 — primary + fallback paths |
| R18.1.2 | Keep termination marker table | ✅ | v3.3.105 — terminal table + edge preserved |

## R19 — L2 Flow Topology: one source, flow targets, every edge on a path (user ruling 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R19.1 | The filtered L2 flow view has exactly one flow source: the searched table.field (the seed) | 📝 design | v3.3.140 seed semantics — the closure root; the source is USER-DEFINED (the search), never inferred; in the full view (no search) origins = read-only tables (read, never written in the script) |
| R19.2 | The flow targets are the output tables the seed's data reaches (DML write targets; pure-SELECT scripts: the terminal output VT). One or more — e.g. the bdm seed reaches sup@160 AND rrcdm@211 | 📝 design | DECISION PROCEDURE: T is a flow target iff (a) T is a DML statement's write target (extraction-time DML attribution) AND (b) T's write leg `output → T` is in the seed's flow closure (reachability walk). A table can be BOTH target and waypoint (sup: target of output1→sup, source of sup→output2) — roles are per-edge/path, unified by physical identity. Requires read recognition (Fix A): without source_tables on bare FROM refs the read of sup is invisible and the target decision breaks (Issue 3) |
| R19.3 | Topological property: every flow edge lies on ≥1 path from the source to some target; no dead-end flow branches; no-bypass — cross-statement flow must route through the reader instance, never shortcut around it | 📝 design | currently VIOLATED at the Issue-3 spot (sup = broken waypoint; the DML WRITE_READ bypasses the statement-2 read) — mandates the Issue-3 fix |
| R19.4 | Structure/containment edges (SCHEMA) are NOT flow — exempt from the path property, rendered visually distinct, their reason explains containment (owner→member by design) | 📝 design | by-design exemption, never forced onto a flow path; hidden by default in the flow view (display toggle), their info lives in the compound-node nesting |
| R19.5 | Full-view (no search) table roles: net-flow classification — a table is a source when flow out dominates (out-edges > in-edges over FLOW edges only, self-loops excluded), a target when flow in dominates; multiple of each; balanced tables = waypoints (BOTH roles, e.g. sup) | 📝 design | L1 roles are edge-decided (cross-script reads/writes — unambiguous); the L2 rule requires read recognition (Fix A: bare FROM reads count as out-flow) |
| R19.6 | No inverse edges in the flow view: (a) structure/containment edges hidden by default (display toggle; payload + benchmark unchanged); (b) synthetic output VTs un-merged by statement (output@L160 / output@L211) so write/read leg pairs never render as inverse — R22 one-node-per-table narrowed to PHYSICAL tables | 📝 design | dissolves Issue-2 Patterns A+B visually; the write leg and read leg are both genuine flow — the inverse look is the label-merge artifact |

## R20 — Path-Scoped Flow Reason (user ruling 2026-08-11)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R20.1 | Every flow edge's reason renders the edge within its complete source→target path: `source@L… → … → ‖own segment‖ → … → target@L…` — upstream walk + downstream continuation, own segment emphasized (existing ‖…‖ wrap) | 📝 design | today the walk stops at the edge's target; leaf/SCHEMA/SUBSET edges show only their own segment |
| R20.2 | The reason explains the edge's role in the scope of its path (write leg / read into output / alias hop / CTE chain …), derived from extraction-time info — never reconstructed at render | 📝 design | extends the current kind + flow-string payload |

## Summary
| Metric | Count |
|--------|-------|
| ✅ Implemented | 75 (all) |
| 📝 Design, not implemented (2026-08-11) | 8 (R19.1–R19.6, R20.1–R20.2) |
| Version | 3.3.145 |

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

