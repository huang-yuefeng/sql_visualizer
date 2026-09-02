# Requirements Traceability Matrix — V3.3.190

> Maps all requirements from REQUIREMENTS.md to implementation status.
> Last updated: 2026-09-02 — **NEW §R54 (the BBZ/p_dt edge rules, USER APPROVED)** — four new
> flow-only edge rules plus the prune that finishes them: **2h** provenance-linked AS-alias
> routing (own-frames admission, F2 — ✅ shipped v3.3.198, USER CONFIRMED as a rule the same day),
> **4e** producer-occurrence anchoring (extractor family 5 + `dependency_graph` Phase 9b,
> `EXTRACTOR_VERSION .14` — ⏳ LANDING v3.3.199/200, uncommitted at doc time), **6d** alias/feeder-box
> scope and **6e** own-segment rule (`_own_segment_carrier` + the 7-A statement-level frame
> carve-out that restores RFN's @768/@1168 write legs — Team SEGMENT's carrier-is-None fix), and
> the **orphan-BOX prune** (3c extended to non-seed boxes with zero remaining edges). Acceptance:
> BBZ 17→10 edges, EAST5 × `p_dt` 7→5, jaccard 20/20 at 1.0000/1.0000; canonical re-pin
> `tests/jaccard_canonical.py` point 27 (5 edge rows + 3 node entries removed). Design decision
> `CLAUDE.md` #60; requirement statement `requirements_v2.md` §"Amendment (2026-09-02) — four new
> L2 flow-only edge rules".
> Prior 2026-09-02 — **NEW §R53 (USER RULING: L2 flow-only-only UI)** — the mode `<select>` is
> removed from the L2 toolbar and the product's only second-level view is the line-merged flow-only
> closure (`flow-merged`, rendered as a static "Flow only" label); the Full view (`full-merged`) and the
> two detailed views (`flow`/`full`) are **CUT FROM THE REQUIREMENT (upgraded from POSTPONED the same day) — source kept, nothing deleted, the two-view API
> payload unchanged, and revival = re-expose the UI + reapply the archived full-view sibling-filter
> patch. Rows AMENDED (annotated in place, history kept): R30.8, R32.1, R32.2, R42.4, R31.26 (2026-09-02
> follow-up: Fit frames the VISIBLE closure — `fitVisibleElements`, E-M8 amended). Requirement
> statement: `requirements_v2.md` §"Amendment (2026-09-02) — L2 flow-only-only UI"; design decision
> `CLAUDE.md` #59. Frontend-only — no backend, no cache, no snapshot, no benchmark change.
> Prior 2026-09-01 (late, doc-hygiene sweep) — **R44.4 and R37.6 flipped ⏳ → ✅**: both verified
> LANDED in the shipped tree against code + tests (evidence in the rows); the ⏳ count is now **0**.
> Prior 2026-09-01 — **v3.3.195 SHIPPED** (release commit `34bd521`, deployed to prod and
> pushed to `origin/main`; HEAD `0ac1c81` retires the 2 lending_ref benchmark deselects). NEW §R46 —
> the canonical ground-truth re-derivation R46c/R46d: the jaccard gate is **20/20 at
> 1.0000/1.0000 recall AND precision**, the two ruled-red `lending_ref` cases are GREEN again and
> their benchmark deselects are retired. NEW §V7 — the two opposite-direction walker admissions
> (g1 over-inclusion, d2 over-filtering), fixed inside the R-GATE with `EXTRACTOR_VERSION`
> deliberately unchanged. NEW §H12 — the physical-model build 45.8 ms → 31.3 ms (−31.6%),
> byte-identical. NEW §"Release gate — the ruled-red deselect policy". R48.5 flipped ⏳ → ✅
> RESOLVED (LFS41/LFS123/LFD2 removed from the canonical by R46c class X5). R44.2, R44.3 and R43.4
> flipped ⏳ → ✅ — the benchmark re-pin and the unified L2 snapshot regeneration both landed at the
> release gate (108 baselines, all green, commit `3777e9e`). R31.35 ✅ SHIPPED. Backend suite
> **1539 passed / 8 skipped / 2 ruled-red deselects** (1549 collected); frontend **438/438 across
> 34 files**.
> Prior 2026-09-01 — **v3.3.195-wave rounds recorded (docs pass): NEW R49 (FSC-2 — the
> physical model is persisted beside the graph cache, so the served closure IS a pure function of
> the SQL text: RFN 28/74 + SUP_M 4/14 alias divergences → 0, and the alias-seed searches that
> fell back to the whole 1053-node graph return their 78-node closure), NEW R50 (H11 Phase 4d-gc —
> the 7 MERGE-column `column_connectivity` defects fixed with a measured blast radius of exactly 7
> corpus-wide edges; the 7 DEFECT waiver entries removed, the 7 FALSE POSITIVE kept; + the G8
> multi-anchor fold), NEW R51 (X1 — the container-PROVENANCE producer pick is a total order, was
> hash-random: 7 pick-sets on RFN; guard 3b removes the 14 direct 2-cycles; the phase is KEPT), NEW
> R52 (M-T1 — TVF alias definition lines, the R37.3/R37.4 L0 gap closed). R31.35 flipped ⏳ → ✅
> (SCR landed: `build_users_env` + comment stripping + the AC7 email log line + the gitignore
> posture; 36 allowlist tests green). R40.13's cross-check gained a round 2 (G9): 45 covered / 12
> justified-missed / 1 wrong-missed (L206, adjudicated as a documented residual) / 4 wrong-covered
> (RC-A still ledgered). Full review record: `wiki/CODE_REVIEW_2026-08-29.md` §10–§16. Prior
> 2026-08-31 — **R31.35 (user management via configuration file — user-approved,
> frozen format + 7 acceptance criteria: `requirements_v2.md` §"Amendment (2026-08-31) — User
> management via configuration file"). (v3.3.194 batch — **fast reopen + incremental index + multi-user
> hardening**, all ✅ LANDED in the working tree and re-verified against the source at doc time:
> NEW R1.9/R1.10 (open = persisted reads via `GET /tree` + `GET /index`; incremental re-index from
> pristine pre-S4b evidence snapshots keyed by the content hash — a zero-diff open issues NO
> `POST /index` at all), NEW R2.12 (the #380 follow-up: participant reads), NEW R3.7 (role-gated
> view "×" + the child-delete routing fix), NEW R14.5 (SSE broadcast per subscriber), NEW
> R31.30–R31.33 (the bounded audit trail, the wedge-proof heavy gate, the role-gated UI, atomic
> writes + meta CAS), NEW R40.14 (self-loop caption retirement + border-scoring assignment).
> R40.13's status cell now records the DONE cross-check: the layer PASSED, acceptance FAILED on
> ENGINE closure defects (RC-A ledgered v3.3.195, RC-B/RC-C in flight with G7/G8 — **both since
> LANDED, see R50.4 and R51**). Audit records:
> `wiki/CODE_REVIEW_2026-08-29.md` §6–§9; requirement-level statement:
> `requirements_v2.md` §"Amendment (2026-08-31) — fast reopen, incremental index, and the
> multi-user hardening batch". Still ⏳ in flight at doc time: G7's RC-C extractor fix, G8's RC-B,
> P2's fit-floor/header. Prior 2026-08-31 (NEW R40.12-A — Field Story rule audit amendment, frontend-only, ✅: `utils/fieldStory.js` re-ruled after a per-field audit of 117 EAST5 pairs / 597 told steps scored 28% true of the field — field-level provenance is now required for every stage, the dead `output_table` ⟐ guard is fixed to the real routing family, an AS-alias production line is a BIRTH and a cross-table value leg a CONSUMED at the DML anchor, and table-path edges are dropped; re-run of the same audit: 95.8%, 0 H defects. 9 residual M defects are walker/index attribution issues listed for the backend follow-up. Full record: the R40.12-A row below and `CLAUDE.md` #37 amendment. Prior 2026-08-31 (NEW R40.13 — string-match diff layer + Field Story browse controls, ⏳ ships v3.3.194: a naive case-insensitive whole-script string-match layer in the SQL panel whose every matched line is color-coded green/red by whether the ENGINE's flow closure covers it, plus `◀ 3/17 ▶` browse controls in the Field Story bar driven by a SEPARATE cursor channel that never touches the R37 engine highlight; boundary rule = lookarounds over `[A-Za-z0-9_$]`, NOT `\b`. Docs written BEFORE implementation (user-ordered); design of record = §"R40.13 — string-match diff layer + browse controls (solution & test plan)"; requirement + acceptance criteria + non-goals = `requirements_v2.md` §"Amendment (2026-08-31)". Frontend-only by design — no backend, no API, no cache, no snapshot change. Prior 2026-08-29 (R44 LANDED + the 2026-08-28 code review adjudicated + the 50-target user-scenario simulation. R44.1 flipped ⏳ → ✅ — occurrence coverage is implemented: write-side/derived-read twins, GROUP-BY twins (`_register_groupby_twins`), OVER-line WINDOW anchors (`highlight_strategies._anchor_line`), l2_builder write-target parenting, R45's family-3 occurrence-line twins (`_collapsed_occurrences`); `EXTRACTOR_VERSION 2026-08-28.3 → 2026-08-28.7` (.7 = the K4 paren-balance diagnostics bump). R44.2/R44.3 stay ⏳ (benchmark re-pin + unified snapshot regeneration). NEW rows: R2.11 (backend case-insensitive search — R2.10's F5 was FRONTEND-ONLY before), R5.13 (#386 CTE statement-scoped visibility ruling), R13.7 (simulation-driven sample repairs), R37.5/R37.6 (K4 VT-anchor amendment / F-B1 field-chip + banner + direction-flip fixes — ⏳), R40.11 (F-B2 chip-decoration guard + banner/autocomplete UX), R44.4 (filter-operand twin edges, F-E1 — ⏳). NEW sections: "K4 rulings (2026-08-28)" and "User-scenario simulation (2026-08-29)". The 2026-08-28 code review's 31 first-pass findings are FULLY ADJUDICATED (23 fixed / 6 false positives / 2 deferrals) — verdict table in `wiki/CODE_REVIEW_2026-08-28.md` §"Resolution status (2026-08-29)". CLAUDE.md's #23/#28/#29 amendments are owned by the F-B1 team and are NOT recorded here yet (pending). Prior 2026-08-28 (v3.3.191+ batch recorded — PENDING RELEASE, landed in the working tree: R40.8 + R41.1/R41.2 flipped ⏳ → ✅ (self-loop curve geometry via data-driven `loopstep`; minZoom 0.28 → 0.08 + `min-zoomed-font-size` 6 + Fit suppresses the seed re-center); new rows R2.9 (F2 CTE index defining-script invariant), R2.10 (F5 case-insensitive name resolution), R5.12 (MERGE targets join the physical fold, #386), R13.6 (RFN sample fully OCR-recovered, #370 — all four samples clean), R40.10 (Field Story Joined/Transformed stage); R40.9's open ruling #380 RESOLVED (creator-only scan/index, 403 participants); R44 added ⏳ (walker occurrence coverage — in flight, NOT yet landed); R43.4 note extended (unified snapshot regeneration at release). Prior 2026-08-28 (R40–R41 added — L2 readability batch v3.3.187–v3.3.190 shipped: filter loop-line anchored to the table border, zoom-compensated caption, Field Story step-through bar, flow-reason panel REMOVED + bar relocated below the SQL panel, cache headers, history slim (re-clone required); multi-user matrix 14 scenarios green with ONE open ruling (#380 index/scan not creator-gated); R40.8 same-table edge + R41 zoom-floor/Fit fixes IN FLIGHT. Prior 2026-08-27 (R33–R36 added ✅ — hover label emphasis, view-open search-params recovery, fit readability margins + zoom floor, release pipeline static-sync guard; shipped v3.3.171–v3.3.178. Prior 2026-08-26 (R32.1–R32.3 flipped ⏸ → ✅ — line-merged views shipped v3.3.166; R1.8 #308 + R31.2 M-Po4 flipped 📝 → ✅ — closed v3.3.165; R31.1 annotated superseded by #293; R31.9 annotated deleted by #322; version bumped to 3.3.166. Prior 2026-08-25: R31 status markers reconciled with shipped code — 8 previously-📝 rows flipped to ✅ against verified implementation; summary recounted: 169 implemented / 1 partial (R31.2 IP audit, pending M-Po4); version bumped to 3.3.164. Prior 2026-08-24: #288/#289 L2 graph backend fixes — case-insensitive physical-table merge shipped; #289 INSERT write-column routing corrected to be a model-following fallback (write columns land on their physical-model owner; only phantom-sourced columns land on the write target); #286 R31 regression fixed — dashboard folder upload restored; R31 status → released v3.3.162, E-series review fixes pending)

## Legend
- ✅ Implemented & verified
- ❌ Not yet implemented
- ⏳ In flight — fix being implemented / queued, not yet verified
- ✂ CUT — removed from the requirement by user ruling (R53, upgraded from ⏸ POSTPONED the same day); implemented and kept in the repo (
  2026-09-02). Not ❌ (nothing was withdrawn) and not ⏳ (nothing is being built): the requirement is
  deferred, its code path and payload contract stay whole, and revival is a UI re-exposure
- A **"(pending release)"** stamp inside an Evidence cell records the state WHEN THAT ROW WAS
  WRITTEN — it does not mean the work is unreleased today. Every row so stamped SHIPPED with
  **v3.3.195** (release commit `34bd521`, 2026-09-01); the last two ⏳ rows (R44.4, R37.6) were
  verified LANDED 2026-09-01 late, so none is outstanding any more

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
| R1.9 | **Fast reopen (P1/P2, v3.3.194)** — opening an existing workspace is a READ, not a rebuild: creator AND participant open read persisted state, and a zero-difference open issues NO `POST /index` at all (zero parses, zero re-extraction). Baseline being removed: every open re-ran the whole extraction pipeline — measured on the 106-pipeline-script `tpcds_qualified` corpus (dev container, v3.3.193) `POST /scan` 0.15 s / `POST /index` 2.28–2.37 s, identical on the 2nd and 3rd open, 70% of it inside `run_full_analysis`, because the per-script analysis caches were REWRITTEN every run and never read back | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `GET /workspace/{id}/tree` serves the A1-classified `file_tree.json` the last index covered (409 on missing/corrupt, never a re-scan); `GET /workspace/{id}/index` serves `table_index.json` + `field_index.json` + `index_report.json` (`{}` on missing/corrupt, never 500). The client decides from the payload's own `freshness` content diff: zero diff → no rebuild call (`openExistingFlow.test.jsx` "a zero-diff open fires no rebuild at all" asserts `indexWorkspace`/`scanWorkspace` never called). Index-panel "Indexed 5m ago" staleness line is passive display |
| R1.10 | **Incremental re-index (P1, v3.3.194)** — an index re-extracts ONLY the scripts that changed; unchanged scripts are REPLAYED from the pristine pre-S4b analysis the previous index persisted. Change detection is by CONTENT, never mtime: the per-file identity is `md5(EXTRACTOR_VERSION + "\|" + rel_path + sql_text)` (truncated 12), recorded in `cache/index_manifest.json` beside the per-script evidence `cache/ixevidence_{key}.json.gz`. S4b and the C-5 star expansion always re-run — they are workspace-wide. **Catch-up flow:** a creator whose open is stale auto-fires one `POST /index`; while it runs the UI shows "Catching up: N changed script(s)…", search is WITHHELD, and index-derived searches answer a retry-able **409** instead of answering from the previous index; the withheld search replays when the run ends. A participant gets an informational hint and never triggers the rebuild | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `folder_index_service.py` `EVIDENCE_PREFIX = "ixevidence_"` / `MANIFEST_NAME = "index_manifest.json"` (`:350-351`), evidence replay decision `:931-939` + restore `:1030-1036`, `index_change_diff`/`get_index_freshness` `:583` (PIPELINE-scoped counts, `None` before the first index, DDL churn in `schema_changed_count`), catching-up registry `:2373-2398`. 409 gates `routers/dataflow.py:213-218,516-520`. UI `DataFlowApp.jsx:468-490` (creator rebuild), `:1456-1470` (the bar), `:697-722` (409 replay). Tests `tests/test_incremental_index.py` (29 — A/B byte-identity of incremental vs full, 0-extraction zero diff, mtime never fools it, add/edit/delete, evidence is pre-S4b, meta CAS, HTTP round-trip) |

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
| R2.12 | **#380 follow-up (AD2-A, 2026-08-31) — a participant can READ the workspace without triggering a rebuild**: `GET /workspace/{id}/tree` and `GET /workspace/{id}/index` serve the PERSISTED index artifacts to any authenticated reader, so opening a shared workspace no longer implies a re-scan. Read-only — no membership side effect (`/resume` is what lands a workspace in the opener's index); missing or corrupt caches answer 409 / `{}`, never 500 and never a silent rebuild. The creator-only rule on `POST /scan` + `POST /index` is UNCHANGED | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `routers/workspace.py:273` (`get_workspace_tree`, docstring "the participant half of Open", serves `cache/file_tree.json`), `:308` (`get_workspace_index`, serves the two index JSONs + `index_report.json` + the `freshness` diff + the `catching_up` flag). Creator-open refreshes them (`DataFlowApp.jsx:458-521` — creator `rebuild()`, participant `setStaleHint(true)`). Tests `tests/test_participant_reads.py` (9) + the matrix in `test_multiuser_workspace.py` |

## R3 — View Management (from requirements_v2.md §3)
| ID | Requirement | Status | Notes |
|----|------------|--------|-------|
| R3.1 | View management tree/bar | ✅ | ViewBar with tabs |
| R3.2 | L1 view = all scripts related to table.field | ✅ | Shows script count badge |
| R3.3 | L2 view = single script detail (child of L1 view) | ✅ | Double-click script node → L2 |
| R3.4 | Remove individual views | ✅ | × button on each tab |
| R3.5 | Multiple concurrent searches | ✅ | Each search creates new view tab |
| R3.6 | + New Search button | ✅ | ViewBar component |
| R3.7 | **View deletion is role-gated and actually routed (v3.3.194)** — (a) the per-view "×" is creator-only (`canManageViews`; `DELETE /views/{id}` is creator-only #272, and the control used to be rendered to participants who then got a silent 403); (b) the L2 CHILD "×" routes to the route that EXISTS — `DELETE /workspace/{id}/views/{childId}`. The previous call addressed a `…/views/{id}/children/{childId}` route that was never implemented, so it 404'd for EVERY role and no L2 child could ever be removed | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `ViewBar.jsx:10-13,42,67` gates the "×" on `canManageViews`, wired `canManageViews={isCreator}` (`DataFlowApp.jsx:1519`); `api/client.js:304-313` `deleteViewChild` → `deleteView` → `DELETE /api/workspace/{wsId}/views/{viewId}` (`:258`); the real backend route is `routers/dataflow.py:337`. Tests `api/__tests__/client.test.js:114-143` ("issues DELETE /views/{childId} — the route that actually exists"), `openExistingFlow.test.jsx:210-265` |

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
| R14.5 | **The SSE log stream BROADCASTS (MSC-6, v3.3.194)** — one bounded queue per SUBSCRIBER, and every producer line is delivered to ALL of them. The previous registry kept ONE ref-counted queue per WORKSPACE, so two participants (or two browser tabs) streaming the same workspace SPLIT the stream: every pushed line was `put` exactly once and therefore drained by exactly one reader — a 13-line diagnostic block reached alice as 1 line and bob as 0, i.e. the LogPanel silently lost a random ~1/N of the stream. Each idle stream also parked a default-executor thread indefinitely | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `services/logger.py` `_log_queues: dict[ws_id, dict[consumer_id, ConsumerQueue]]` (`:33-43`, no separate ref counter — the live-consumer count IS `len(...)`); `register_queue` returns the subscriber's OWN queue (`:196-213`), `unregister_queue` removes exactly that consumer (`:216-238`), `_push` snapshots the consumer set under the lock and delivers to all (`:178-190`), never recreating a dropped queue (bug M7); bounded `_MAX_QUEUE = 500` per consumer with drop-oldest (`:127-150`) + `dropped_line_count()`; `ensure_queue` is a deprecated shim. Router side `routers/logs.py:34`. Tests `tests/test_logger_broadcast.py` (14 — both subscribers get EVERY line, unsubscribe isolation, a slow consumer never blocks the producer, no parked executor thread, two live streams each get the whole block) |

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
| R30.8 | L2 single-view visibility toggle (View 1 flow-only ↔ View 2 full) **— AMENDED 2026-09-02 (R53): the toggle is CLOSED in the UI, the flow-only side is the only L2 view; the toggle code path is kept, CUT** | ✅ | #247 — v3.3.160 — in ONE open L2 view, a checkbox toggles between View 1 (only the searched field's flow closure: `flow_node_ids`/`flow_edge_ids`) and View 2 (the full script graph); pure `.show()/.hide()` visibility — positions preserved, never a re-layout. **2026-08-24 (user ruling)**: the toggle label must be English — "Flow only" (the button previously read a Chinese label meaning 'target-field flow only') — see #290. **2026-09-02 (user ruling, R53)**: the user-facing entry is closed — the product ships the flow-only view only; the payload contract and the visibility machinery stay in the repo for FULLVIEW's revival |
| R30.9 | Case1 autocomplete EAST5_SSTZFXXB fix | ✅ | #245 — v3.3.160 — Case1 table autocomplete fixed for EAST5_SSTZFXXB |
| R30.10 | C-H1 L1 cache staleness guard | ✅ | #248 — v3.3.160 — L1 cache staleness guard added |
| R30.11 | ROW_FLOW — the 17th edge type: row-level flow bridge emitted by the L2 walker's R29 continuation (the searched field's row-selection effect into a downstream statement's rows, e.g. subquery output `⟐ t` → CTE `temp_kmbh_gl`) | ✅ | #226 — v3.3.155 — flow-class edge (arrow + highlightable), shares the uniform line style; `ROW_FLOW` in `EDGE_TYPE_STYLE` (#2ECC71 solid width 2) + category "flow" (`backend/app/services/graph_service.py`), documented in `sql_model.py`, emitted by `compute_field_flow`'s continuation rounds (`backend/app/extractor/lineage.py`), rendered "row flow" by `highlight_strategies.py` |

## R31 — Multi-user identity & workspace collaboration (2026-08-19, RELEASED v3.3.162)

> Design note `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md`. Released v3.3.162 (task #251). **R31 backend follow-ups (2026-08-24, Team A) — all RESOLVED:** #269 config-provisioned users only (admin endpoint removed), #270 bare `DELETE /api/workspace` removed, #272 L2 layout persistence + creator-only layout editing, #273 heavy-op gate wired in, #279 zero session expiry, #280 same-origin kept (documented), #285 per-user visit logging dropped (+ #278/#281). **R31 frontend follow-ups (2026-08-24, Team B) — all RESOLVED:** #276 shared 401 session-expiry interceptor (E-M1), #277 per-user localStorage namespacing (E-M2), #282 L2 child-delete drops to L1 (E-M7), #283 auto-fit bounds ALL nodes (E-M8 — AMENDED 2026-09-02: Fit frames the VISIBLE closure, see R31.26), #284 resumeLayouts updated on save (E-M9), #291 L2 READ path applies saved positions, #292 view tree restored on open, #295 workspace management merged into the debugger left panel. #286 (2026-08-24): dashboard folder-upload regression fixed (see R1.2). #293 (2026-08-24): login merged into the debugger left panel (R31.15). **R31.35 (2026-08-31, ✅ LANDED 2026-09-01 — the script team SCR, v3.3.195 wave): user management is FILE-driven** — `users.allowlist.json` at the repo root is the source of truth for the whole allowlist, and `target_deploy.sh` strips its `//` comments, auto-merges `admin@hsbc.com` and activates the accounts at deploy (formalizes the #269 config semantics below; the R31 model itself — provisioned users, creator/participant roles — is unchanged). Implementation + test pointers on the R31.35 row

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
| R31.11 | **Password recovery = admin-mediated reset** (no self-service path overwrites an identity, A-H1); with #269 the ONLY path is re-provisioning from config (`PROVISIONED_USERS`, force-synced at every startup) — no HTTP reset endpoint | ✅ | R31 (2026-08-19) — #269 config provisioning (2026-08-24). **R31.35 (2026-08-31)** is where that config comes from: the file `users.allowlist.json` is the source of truth and `target_deploy.sh` auto-merges admin and activates it at deploy — so a password change IS an edit to the file plus a deploy |
| R31.12 | **One global heavy-op gate** (debugger search + `/analyze` + `/analyze_multi` + diagnostic `/workspace/{id}/debug/graph`): while one runs, a new one returns HTTP 409 "system busy — please wait" | ✅ | R31 (2026-08-19) — **#273 (2026-08-24) wired in**: `heavy_gate.gate` singleton gates all heavy ops; CPU-bound work moved off the event loop (`asyncio.to_thread`). 2026-08-25: code-review M-P1 wrapped the diagnostic `debug/graph` endpoint in the same gate |
| R31.13 | **Migration**: pre-feature workspaces (no creator) removed directly at rollout; concurrent same-file write loss **accepted** (low concurrency) with atomic temp+rename so files never corrupt | ✅ | R31 (2026-08-19) — `remove_legacy_workspaces()` in the lifespan (no-op once none remain); temp+rename accepted-loss writes (A-M3) |
| R31.14 | **#292 L1/L2 view tree not restored on opening a stored workspace** — the left-panel view tree (search views + their L2 children) is persisted server-side in views.json but the frontend never loads it on open (`listViews` in `frontend/src/api/client.js` is defined but never called; `handleOpenExisting` in `frontend/src/DataFlowApp.jsx` does resume→scan→index and skips views) | ✅ | #292 (2026-08-24) — `handleOpenExisting` calls `api.listViews(wsId)` after index and `setViews(viewsRes.views)`; no auto-activate (R23 clean start) |
| R31.15 | **#293 Login merged into the data flow debugger's left panel** — the full-screen LoginPage gate is removed; the login form lives in the debugger's left panel. ONLY the Data Flow Debugger requires login — SQL Analysis (legacy `/api/analyze`, `/api/analyze_multi`, `/api/scripts`) is public (exempt from the `login_gate` middleware via `PUBLIC_API_PREFIXES` in `backend/app/main.py`). Caveat: `DELETE /api/scripts` (clears the analysis cache) also becomes public — accepted for an internal tool | ✅ | #293 (2026-08-24) — shipped v3.3.164; login form in the debugger left panel, SQL Analysis public |
| R31.16 | **#269 Config-provisioned users only** — the gate-exempt `POST /api/admin/users` bootstrap (E-H1/E-H3) is REMOVED; `/api/admin` is gone from `PUBLIC_API_PREFIXES`. Accounts are provisioned from `config.PROVISIONED_USERS` (default `admin@hsbc.com` / `123456`, env-overridable via `PROVISIONED_USERS_JSON`) at startup — `main.py` lifespan force-syncs every entry. No HTTP endpoint provisions users | ✅ | #269 (2026-08-24) — R31 backend Team A. **R31.35 (2026-08-31) formalizes where that env value comes from**: `users.allowlist.json` at the repo root is the source of truth for the WHOLE allowlist, and `target_deploy.sh` strips its `//` comments, auto-merges `admin@hsbc.com` and passes the merged JSON as `PROVISIONED_USERS_JSON` at deploy — the env var stays the transport, the FILE is the truth |
| R31.17 | **#270 bare `DELETE /api/workspace` (cleanup-all) removed** (E-H2) — the endpoint and `cleanup_all_workspaces()` are deleted; no session can rmtree every workspace + the notifications dir | ✅ | #270 (2026-08-24) — R31 backend Team A |
| R31.18 | **#272 L2 layout persistence + creator-only layout editing** (E-H4) — the `opened_l2s` prune that silently dropped every `l2:{script}` layout is removed (L2 drag positions now persist; also fixes #291). `PUT .../layout` is now creator-only — a non-creator session gets 403 | ✅ | #272 (2026-08-24) — R31 backend Team A |
| R31.19 | **#273 heavy-op gate wired in** (E-H5) — `heavy_gate.gate` (module singleton) gates debugger search + `/analyze` + `/analyze_multi` + the diagnostic `/workspace/{id}/debug/graph` (M-P1, 2026-08-25); while one runs a new one returns **409 "system busy — please wait"** (released in a finally). CPU-bound work moved off the event loop via `asyncio.to_thread` | ✅ | #273 (2026-08-24) — R31 backend Team A; M-P1 (2026-08-25) wrapped the debug endpoint. **Amended by R31.31 (2026-08-31)**: the singleton still serializes, but the per-call acquisition state that used to live on it moved to a per-call token — the singleton's own state was the MSC-1 wedge |
| R31.20 | **#279 ZERO session expiry** (E-M4) — the 30-min absolute `max_age` cookie and the idle-reaper/`last_active` extension are removed. The session cookie has no `max_age` (the browser drops it on close); in-memory sessions live until logout or server restart (A-M9 accepted) | ✅ | #279 (2026-08-24) — R31 backend Team A |
| R31.21 | **#280 Same-origin check kept as defense-in-depth** (E-M5 decision) — NO code change. SameSite=Lax is the real boundary; the origin check stays; the accepted no-Origin / `Origin: null` bypass is documented. The Low CORS `allow_origins=["*"]` item stays out of scope | ✅ | #280 (2026-08-24) — R31 backend Team A (decision recorded) |
| R31.22 | **#285 Per-user visit logging dropped** (E-H6/E-H7/E-M3/E-M6, folds #278/#281) — `visit_service.py` deleted; `open_visits` registry, `open_visit`/`touch_visit`/`flush_session_visits`, visit memos/creator-alerts and all visit `append_activity` calls removed. `close_workspace` is a **no-op returning 200** (frontend `closeWorkspace` kept). Only creator-driven activity events (workspace create/delete/remove-from-history) remain | ✅ | #285 (2026-08-24) — R31 backend Team A |
| R31.23 | **#276 Shared 401 session-expiry interceptor (E-M1)** — `api/client.js` wraps every gated fetch in `gatedFetch`; a 401 from any gated endpoint (not login, not the public analysis endpoints) fires the module-level handler — registered by AppShell on mount via `api.onSessionExpired(cb)` — exactly once per 401 batch, dropping the session (`me=null` → the login form re-renders in the dataflow left panel). No redirect-reload | ✅ | #276 (2026-08-24) — R31 frontend Team B |
| R31.24 | **#277 Per-user localStorage namespacing (E-M2)** — search history/pins keys are now `df_search_history:{username}` / `df_pinned_searches:{username}`; the username flows AppShell → DataFlowApp → FilterPanel. Global keys (theme, the one-time `df_last_search_view` purge) are left untouched; no other per-user `df_*` keys found | ✅ | #277 (2026-08-24) — R31 frontend Team B |
| R31.25 | **#282 Deleting the active L2 child view drops back to L1 (E-M7)** — `handleDeleteView` detects when the deleted view (or its L2 parent) is the active view and clears graphLevel('L1'), l2Result, flowOnly, sqlText, currentScriptName, selectedEdge, l2NotInFlow*/l2ParseErrors, activeViewId | ✅ | #282 (2026-08-24) — R31 frontend Team B |
| R31.26 | **#283 Auto-fit bounds ALL nodes (E-M8)** — `fitAllElements` in `flowVisibility.js` shows every element, calls `cy.fit()` on the full closure, then re-applies flow visibility (preserves D-H2 ordering: fit after the flow-visibility apply). **— AMENDED 2026-09-02: Fit bounds the VISIBLE closure** — `fitVisibleElements` (renamed from `fitAllElements`) applies the flow visibility pass FIRST, then `cy.fit(cy.elements(':visible'), padding)`; the full-model fit is retired with the Full view (R53), which is what made hidden-element framing pointless — hidden elements are unreachable by any UI path. History kept: the original order above is what shipped 2026-08-24 → 2026-09-01 | ✅ | #283 (2026-08-24) — R31 frontend Team B. **AMENDED 2026-09-02** (E-M8, under the R53 flow-only-only ruling — `CLAUDE.md` #59): requirement statement in `requirements_v2.md` §"Amendment (2026-09-02) — L2 flow-only-only UI" §"Fit frames the VISIBLE closure". Pins: `flowVisibility.test.js` (the fake `cy` honors `elements(':visible')`; the fitted collection is exactly the visible closure `['e1','n1','n2']`), `fitZoomException.test.js` (the FIT-only zoom floor lift still applies to the same hook Fit path) |
| R31.27 | **#284 resumeLayouts updated on layout save (E-M9)** — on layout save success (and 409 fresh-state refresh) `flushLayoutSave` folds the just-saved positions into `resumeLayouts` under the exact `l1` / `l2:{script}` key so re-open applies LATEST positions; `resumeLayoutKey()` (utils/layoutPersistence.js) is the single source of truth for the save/read key | ✅ | #284 (2026-08-24) — R31 frontend Team B |
| R31.28 | **#291 L2 READ path applies saved positions** — L2 open reads `resumeLayouts[resumeLayoutKey('l2', currentScriptName)]` (was mismatched vs the `l2:{script}` save key); together with #272 (backend prune removed) and #284 (frontend resumeLayouts update) L2 drag persistence round-trips | ✅ | #291 (2026-08-24) — R31 frontend Team B |
| R31.29 | **#295 Workspace management merged into the debugger left panel** — the standalone MyWorkspaces dashboard is retired; AppShell always renders `<DataFlowApp>` when logged in; a "My workspaces" section sits at the top of `.panel-left` (list + 📁 Select Folder + zip upload + open-by-id); upload → `api.uploadWorkspace(file)` then `onOpenWorkspace(result.workspace_id)`; WorkspacePanel gets `showUploads={false}` so no second upload picker appears | ✅ | #295 (2026-08-24) — R31 frontend Team B |
| R31.30 | **MSC-3 (2026-08-31) — the per-workspace activity trail is a real trail**: the History panel labels itself "who did what", but #285 had dropped visit logging and the other actions were never written, so the file held exactly ONE record (`workspace_created`) no matter what a participant did. The full action set the server actually performs is now written — `workspace_created`, `visit_start`, `search`, `l2_opened`, `layout_saved`, `visit_end`, creator `scan`+`index` — for real sessions only (synthetic `dev-user` traffic with the login gate off is never an actor), atomically appended, and BOUNDED at the last 200 records (the MSC-5 views.json lesson: a busy shared workspace must not grow a per-workspace file without limit) | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `services/audit_service.py` (`ACTIVITY_CAP = 200`, detail clipped to 200 chars, `_trim_to_cap` under a per-workspace `.activity.lock` flock, the trim's `os.replace` swaps the inode so the lock is held on the DOTFILE, `atomic_write_text`); hook points `routers/workspace.py:118,216,240,369,404,481` + `routers/dataflow.py:278,300,465`, funnelled through `_audit` (`workspace.py:50-80`). Note: workspace CLOSE is recorded as `visit_end`, not as a `close` action. Tests `tests/test_audit_trail.py` (16 — the record set with the right actor per record, what must NOT be recorded, the exact-cap invariant, clipping, 0600, concurrent appends + simultaneous trim) |
| R31.31 | **MSC-1 (2026-08-31, CRITICAL) — the heavy-op gate is wedge-proof**: `HeavyGate` kept per-call state (`self._acquired`) on the MODULE-LEVEL SINGLETON every heavy-op endpoint shares. A second — 409-refused — entrant overwrote the holder's `True` before the holder unwound, so neither `__exit__` called `release()` and the module global `_busy` stayed True FOREVER: every search, any user, any workspace (and every `/analyze`) answered 409 "system busy — please wait" until the container restarted. Reproduced live at 0% CPU after one concurrent burst | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — the acquisition lives on a per-call `_GateToken` holding ITS OWN `acquired`/`released` flags, kept on a per-thread LIFO stack (`threading.local`); `__exit__` releases only what ITS OWN `__enter__` acquired, once. The singleton `gate` and the one global `_busy` under `_lock` stay — the serialization is unchanged, only the bookkeeping moved; `__bool__` preserves the routers' `with gate as acquired: if not acquired: 409` shape. Amends R31.12/R31.19 (which described the singleton as the mechanism). `services/heavy_gate.py:13-19,45-70,79-113`; tests `tests/test_heavy_gate.py` (12 — the deterministic wedge sequence, overlapping enters, a refusal never touches the holder, bursts, nested/double-exit idempotency, exception-inside-gate release, 8-thread hammer) |
| R31.32 | **Role-gated UI (v3.3.194)** — (a) the workspace action is LABELLED BY ROLE because the same endpoint does a different thing: creator "Delete Workspace", participant "Remove from my list" (the old unconditional "Delete Workspace" mislabelled the participant case); (b) there is NO manual re-index control for ANYONE (user ruling 2026-08-31) — the automatic content-hash catch-up (R1.10) is the only re-index UI, and corrupt/missing caches fall back to a full build on open | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `components/WorkspacePanel.jsx:11-13` ("There is NO manual re-index control by design") and `:113-127` (`isCreator ? 'Delete Workspace' : 'Remove from my list'`); per-view gating is R3.7. Tests `components/__tests__/WorkspacePanel.test.jsx:34-47` (asserts both labels AND that no `reindex-btn` exists for anyone), `__tests__/openExistingFlow.test.jsx:201-228` |
| R31.33 | **No torn state under concurrency (v3.3.194)** — every index/cache/meta write is atomic (unique temp file + `os.replace`), `filtered_index.json` is refreshed or cleared on every index, and `meta.json` state-version updates are a compare-and-swap under a process-wide `_meta_cas_lock`. A concurrent reader sees the whole old artifact or the whole new one, never a half-written one — previously a participant reading during a creator re-index could hit an intermittent 500 or, worse, a silently EMPTY index served as the truth | ✅ | v3.3.194 batch (landed, SHIPPED v3.3.195) — `services/atomic_io.py` (`atomic_write_text`/`atomic_write_bytes`, promoted from `dataflow_service._atomic_write_text`, which now delegates); callers `folder_index_service.py:13,403,432` (index, report, manifest, evidence .gz, file_tree), `dataflow_service.py:448,585,602,783` (schemas, graph cache, views.json), `filter_service.py:358-364` (`filtered_index.json`, off-loop), `audit_service.py:34,132`; `filtered_index` refresh/clear `folder_index_service.py:1704-1722` (`filtered_index_cleared` in the response); CAS `workspace_service.py:169,175-211` + the retry-on-stale loop `folder_index_service.py:1745-1757`. Proof has teeth: `tests/test_multiuser_workspace.py` re-runs the same harness with the atomic write REMOVED and reproduces the tear; meta CAS in `test_incremental_index.py:620`. Residual: `_write_meta_cas_locked` (`workspace_service.py:208-210`) still hand-rolls its own temp+replace instead of calling `atomic_io` (cosmetic — same shape, no OSError cleanup) |
| R31.35 | **User management via configuration file (2026-08-31, user-approved, HIGHEST PRIORITY)** — ALL service users are manually configured in ONE file, `users.allowlist.json` at the repo root next to `target_deploy.sh`; a deploy loads that file and activates its users. The LIVE file is GITIGNORED (real passwords never pushed) and a committed `users.allowlist.json.example` documents the format (never real passwords). **Format (frozen)**: a single JSON object mapping email → password — `{"admin@hsbc.com":"123456","alice@hsbc.com":"alice-pw2"}` — with `//` line comments supported (stripped by `target_deploy.sh` before parsing). **Rules (pre-existing R31 semantics, now file-driven)**: the file is the WHOLE allowlist (`config.py` semantics: the parsed object REPLACES the default, never merges with it); passwords ≥ 6 chars enforced at startup, a shorter entry SKIPPED with a named WARNING (M1-D4); `target_deploy.sh` AUTO-MERGES `admin@hsbc.com` / `123456` when the file omits it (M1-D5 closed); deploying re-syncs the listed accounts (new = created, existing = password re-synced + live sessions revoked, M-Po7) and touches no workspace, view or index (the durable `gps_workspace_data` volume). Requirement statement + the frozen format + the 7 acceptance criteria + non-goals: `requirements_v2.md` §"Amendment (2026-08-31) — User management via configuration file (R31.35, highest priority)"; design decision `CLAUDE.md` #49 | ✅ | LANDED 2026-09-01 — the script team SCR's v3.3.195-wave batch is in the working tree. `target_deploy.sh` `ALLOWLIST_FILE="users.allowlist.json"` + `build_users_env` (prints the merged JSON and sets `USERS_ENV_STATUS` / `USERS_ENV_JSON`; called BARE — a subshell would drop the status and the deploy would silently provision nothing; its stdout is DISCARDED because that copy carries the PASSWORDS and must never reach the console or a tee'd deploy log) + `strip_allowlist_comments` (`//` FULL-LINE comments only, optional leading whitespace; CR/LF/TAB removed so a pretty-printed commented file parses); statuses `ok` / `merged-admin` produce the `-e PROVISIONED_USERS_JSON=…` hand-off, every other status was already logged as a WARNING + SKIP and the deploy continues with the image default; a post-deploy step names the provisioned accounts by EMAIL, never the password. `config.py:42-50` (the parsed dict REPLACES the default allowlist); startup force-sync `main.py:184-185` → `auth_service.provision_user(force=True)` (`MIN_PASSWORD_LEN = 6`, the create-or-re-sync + the rejection WARNING that names the account, session revocation). **Gitignore posture**: `.gitignore:43-45` + the committed `users.allowlist.json.example` (the live file is untracked). Tests: `tests/deploy/test_allowlist_logic.sh` — **36 passed, 0 failed** (comment stripping, admin auto-merge omitted vs listed, empty/invalid/missing file → image default + warning, short password → skipped + named warning, no password value in any log, the subshell trap, the entry guard) — re-run by the 2026-09-01 documentation pass. The three "still to land" items of the previous note (comment stripping, the AC7 email log line, the gitignore/`.example` posture) are all closed |

| R32.1 | **L2 flow-only-merged view** — over the flow-only closure: every field edge is promoted to its table edge (field endpoint → parent table, never dropped); same-line same-table-pair edges merge into one; edge type removed (single untyped `flow` edge); direction = single arrow (one direction) / double arrow (both directions), never two separate opposite edges; self-loop kept only when it is the line's sole edge, otherwise absorbed; an edge with no SQL-line reference is dropped; a line spanning >2 tables emits one edge per pair. Node set identical to flow-only. **AMENDED 2026-09-02 (R53): this is now the product's ONLY L2 view** | ✅ | #329 — SHIPPED v3.3.166 (2026-08-26); the sole user-reachable L2 view since the 2026-09-02 ruling (R53) |
| R32.2 | **L2 full-merged view** — same merge rule as R32.1 applied over the full graph. **AMENDED 2026-09-02 (R53): CUT FROM THE REQUIREMENT — no user entry point, none planned; the code path, the payload contract and this row all stay** | ✂ CUT | #329 — SHIPPED v3.3.166 (2026-08-26) and user-reachable until the 2026-09-02 ruling (R53) closed the UI entry; engine + payload unchanged, revival = re-expose the UI (+ the archived full-view sibling-filter patch) |
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
| R37.3 | Guards | ✅ | Scroll only when `line_start` is an integer ≥ 1 — else silent no-op (never guesses; K4.4). The ledger M-T1 gap is CLOSED — see R52: the TVF alias now anchors on its own call line, so the L0 no-op no longer triggers on it. First line only (statement spans would need new node payloads — deferred). L2 only (L1 cross-script SQL is different machinery). Node click clears any stale edge reason-panel selection |
| R37.4 | Every table node's line number audited against the sample SQL | ✅ | EAST5 full view: all 25 table nodes checked (physical → line mentions the table; ⟐ VT → statement anchor keyword; alias → FROM/JOIN + alias token). Result at audit time: 24/25 exact; the 1 gap = TVF alias `f` at L0 — CLOSED by R52 (M-T1, the `skip_parens` def-site run) |
| R37.5 | **K4 ruling 1 — the ⟐ VT anchor is the CREATION line** (contract AMENDED; the code was already right): a top-level ⟐ output VT anchors on the statement's OWN first token — never the `WITH` line; a nested subquery/derived/EXISTS ⟐ VT anchors on the body's first output line (falling back to the body's SELECT head) | ✅ | 2026-08-28 (K4) — amendment only, no code change; R37.2's "statement anchor line" wording is now precise. Recorded as a design decision in the "K4 rulings" section below |
| R37.6 | **F-B1 (2026-08-29) — click-to-SQL channel completeness**: field chips carry `line_start` (never `line_end`) from the served payload, the not-in-flow banner text states WHY nothing highlighted, and the direction default flip lands with it | ✅ | **LANDED — verified in the shipped tree 2026-09-01 (doc-hygiene sweep)**. Chip payload: `l2_builder.py:1120-1127` (K4 ruling 1 FIX-DEFECT — the chip carries `line_start` ONLY, keeper = first occurrence; `line_end` would re-route `pickAutoEdge`'s priority-1 seed-zone pick) + `frontend/src/hooks/useCytoscapeGraph.js:340-352` ("F-B1 now puts a valid `line_start` on every chip"). Banner/notice: `frontend/src/DataFlowApp.jsx:1114-1117` and `:1143` set the "this element has no SQL line" notice (rendered `:1815-1817`), and the not-in-flow message states the truthful reason — `dataflow_service.py:738`. Direction default flip: `frontend/src/api/client.js:230-235` (default `'downstream'`), `frontend/src/DataFlowApp.jsx:63-68` (toggle removed, `const direction = 'downstream'`), `routers/dataflow.py:39-53` (`_normalize_direction` coerces omitted/legacy "upstream" → "downstream"). Tests: `backend/tests/test_k4_rulings_fb1.py` — `TestFieldChipLineStart` (`test_every_field_chip_carries_line_start` / `test_field_chip_never_carries_line_end` / `test_seed_chip_anchors_at_first_occurrence_line` / `test_chip_line_lights_the_definition_via_level2_response`), `TestDirectionDefaultDownstream` (`test_service_and_builder_defaults_flipped`, `test_legacy_upstream_is_coerced`), `TestNotInFlowMessage::test_message_says_downstream_flow_not_not_queried`; frontend `src/utils/__tests__/nodeClickScroll.test.js:61`, `src/__tests__/storyStepNotice.test.jsx:156,176`. The CLAUDE.md side-amendments also landed (K4.2 paren-balance, K4.3 direction-never-honored) |

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
| R40.12-A | **Field Story rule audit amendment (2026-08-31)** — the user-facing classification was audited per field and re-ruled: a story step is told ONLY when the payload carries FIELD-level provenance for the searched field, i.e. an edge endpoint that is one of the searched field's OWN chips (the seed plus every occurrence twin of that field on the searched compound) | ✅ | 2026-08-31 (frontend-only, `utils/fieldStory.js`; no backend, no payload, no snapshot change). Evidence: 117 searchable `(table, field)` pairs of EAST5_STZFXXB_M.sql → 597 told steps, 167 true of the field (**28%**; birth 3/49, read 0/95, consumed 32/267, joined 51/105; written/reappears/filtered 100%), ground truth = the script text + a hand-verified token/alias model built independently of the module. Four rules re-ruled — **Fix H**: `consumed` had no field-leg requirement and its ⟐output exclusion tested `type === 'output_table'`, a type absent from served payloads (real routing intermediates are `intermediate_table`, so the guard was dead) → the routing family is now matched by type AND the `⟐` name marker, a value leg must be SOURCED by one of the field's chips, and the leg is resolved through the routing intermediate's single outgoing write leg (no single leg → untold): own table ⇒ **birth** at the value leg's own line (the AS-alias/PARTITION production line, e.g. `… AS cjrq` @74), other table ⇒ **consumed** at the consuming DML statement's line (the intermediate's `line_start`, never the production line), the routing leg riding the step's evidence; **Fix M table-path**: no chip endpoint ⇒ no step (191 TABLE-PATH + 52 PHANTOM steps); a read also needs the chip to SOURCE the leg (`compound → chip` value copies 8/8 wrong) at the chip's own `line_start`; joined/filtered need a line that is neither the compound's anchor nor, for JOINISH types, the chip's own line (a JOINISH edge there is that line's own expression ⇒ told as `read`; a FILTER there IS the field's predicate ⇒ stays `filtered`); **Fix M birth**: `highlight_line === the table's line_start` is no longer the birth test (it is the FROM/JOIN anchor for a source table — 46 fake births — and never the AS-alias line), a source-side field has NO birth stage (its honest stage is `read` at first occurrence), and a birth line absorbs the other chip edges on that line. Re-run of the SAME audit over the SAME 117 payloads: **207/216 = 95.8%** (birth 61/61, read 34/34, written 63/63, reappears 14/14, filtered 4/4, joined 10/13, consumed 21/27), **0 H defects** (was 138), 597 → 216 steps, 116/117 stories non-empty. Scored by the audit's published engine unchanged: 69% — the whole delta is that engine's birth branch, which had no OK case for a target column's AS-alias line while its own `correct` field said `birth @L74`; this amendment rules the AS-alias line IS the birth (Fix 1c). The 9 residual M defects need payload fields that do not exist client-side: 6× a SELECT-output alias attributed to a SOURCE table (`bz`←`a.ccy_code`, `RESERVED_6`←`A.Reserved_Field18`, `dkje`←`b.loan_amt`, `nbjgh`←`b.org_no`, `xdhth`←`b.contract_no`, `xdjjh`←`b.lending_ref` — the walker builds a value leg for the alias chip) and 3× a COMPUTED edge addressed to the wrong output chip (`@51` → `stzfdxhh`, `@71` → `RESERVED_8`/`RESERVED_10`); backend follow-up = stop attributing output aliases to source tables / fix the expression→output addressing, or expose the per-edge field hop (today only inside the display `reason` string) as structured edge data. Flagship regressions hold: the 9 R40.12 examples keep exactly their audited reappears steps, dm_flag2 RFN keeps written-768/written-1168 (its two ⟐-routed "consume" legs drop — they carry no dm_flag2 chip). Tests: `fieldStory.test.js` rewritten for the corrected canonical closure (3 steps for `east5_stzfxxb.p_dt`) + one suite per new rule; 398 frontend tests green (was 384). Full record: `CLAUDE.md` #37 amendment |

| R40.13 | **String-match diff layer + Field Story browse controls** — after a search, the SQL panel also shows a NAIVE case-insensitive string-match layer over the WHOLE script (comment and string-literal lines included), every matched line color-coded by whether the ENGINE's flow closure covers it (covered = green band, not covered = red band) with the counter "N string matches · M in flow · K not in flow"; the Field Story bar gains `◀ 3/17 ▶` browse controls that walk the matched lines through a SEPARATE cursor channel — never the R37 engine-highlight channel | ✅ | 2026-08-31 — **IMPLEMENTED in the working tree (frontend-only; ships v3.3.194).** Requirement + acceptance criteria + non-goals: `requirements_v2.md` §"Amendment (2026-08-31) — R40.13 string-match diff layer + Field Story browse controls". Design of record, boundary-rule verification, solution sketch, resolved ambiguities and test plan: §"R40.13 — string-match diff layer + browse controls (solution & test plan)" below. Frontend-only BY DESIGN: no backend change, no API, no cache, no snapshot change, no correctness claim about the engine. Fixture VERIFIED live on `east5_stzfxxb.p_dt` (engine claim from the committed closure snapshot, `l2_snapshot_04_EAST5_STZFXXB_M.sql.json` = closure lines {41, 179, 189, 190}): 12 naive match lines → the counter reads exactly "12 string matches · 2 in flow · 10 not in flow", L41/L190 banded green, L166–175 (the ten R43 partition-DDL lines) banded red; engine channel untouched while browsing; the counter and bands are identical in the full and merged views (AC5). 42 new vitest tests (`stringMatch.test.js` + SqlPanel/FieldStoryBar suites), 398 frontend tests green. Three sketch-level corrections recorded in CLAUDE.md #45: the CSS selectors are the compound `.sql-line.string-match.covered|missed` forms (the sketch's `.string-match-covered` literal matches nothing of the documented `string-match covered` class list), the field name resolves through the PARENT search row (`storyTarget.field` — `activeView` is the L2 child row and carries no field), and the bar wraps the cluster onto its own row so the counter is never clipped in the default 420px L2 panel. **2026-08-31 cross-check DONE** — the 10-difficult-case acceptance run adjudicated 62 SQL lines (36 correct-covered / 11 correct-missed / 11 wrong-missed / 4 wrong-covered) and the LAYER PASSED every one of them: each band it painted was a true statement about the difference between the naive grep baseline and the engine's flow closure, which is all AC1/AC7 claim. Acceptance FAILED on ENGINE closure defects (root causes RC-A ledgered v3.3.195, RC-B/RC-C in flight with G7/G8) — the feature is a comparison aid, not a correctness claim, exactly as the non-goals below state. Record: `wiki/CODE_REVIEW_2026-08-29.md` §8. **2026-09-01 round 2 (G9), after G7/G8 landed:** the same 62 lines re-adjudicated **45 correct-covered / 12 justified-missed / 1 wrong-missed / 4 wrong-covered** — the 9 wrong-missed lines G7 (the container-PROVENANCE bridge) and G8 (the multi-anchor fold) lit; the missed class is split so a legitimate engine exclusion (the R43 partition-DDL shape, the `rrcdm_job_log_exec_par` routing) is no longer lumped with a correct miss; the ONE surviving wrong-missed is **L206**, adjudicated as a DOCUMENTED RESIDUAL rather than a defect (a join predicate on the field's NAME, not its value — the raw model DOES carry the edge, the R-GATE declines to admit it, and the pin `test_v4_walker_batch.py::test_l206_join_predicate_residual` makes a later ruling start from a failing test); the 4 wrong-covered stay **RC-A, still ledgered**. The per-line verdict table is transcript-only (no repo artifact), as in round 1 — record: `wiki/CODE_REVIEW_2026-08-29.md` §15 |
| R46a | **Target scoping — `is_target` is the seed claim of the searched table's own compounds (FSB audit, EAST5, 168 pairs)** — searching `bdm_acc_entrusted_payment.data_dt` stamped `is_target` on the `data_dt` chips of b, c, d and e too (54 phantom seed chips across 41 pairs): the seed predicate was owner-agnostic, so every same-name chip of every table in the joined statement claimed the seed. **Ruling (AD3, 2026-08-31, amended by coordinator same day):** `is_target` = the chip's field-part equals the searched field AND the chip's parent compound is EITHER an entity of the searched table's entity set (the walker's own W1 seed rule: `target_keys ∪ _tkeys_ci ∪ _alias_keys`, the #399 alias expansion included) OR a DML write-target compound that RECEIVES the searched field's value (the R44 family-1 write twins — "only the field involved in the data flow is shown" cuts both ways). READ-side same-name chips on other tables' compounds (the FSB phantoms — join partners' partition columns) are ordinary nodes: their compounds never receive the value, they only compare with it. **Implementation:** `l2_builder._scope_target_stamp` runs at the DISPLAY boundary in `_build_l2_graph` (after every edge consumer has read the flag, before assembly) — `is_target` is load-bearing inside the build (P2 `_promote_field_edges` and P17 `_simplify_dml_edges` keep a seed field's edges at field level; `_attach_flow_payload` walks the closure from the seed entries), so gating the flag in the seed phase re-routed SERVED edges (measured: the J12-15 trunk flagship lost its rrcdm write leg; J1's LFS129 own-field value copy went dark). The narrowing only ever REMOVES a stamp; the served EDGE sets stay byte-identical (pinned per pair). Support: `_searched_entity_keys` (the walker's W1 entity set, #399 expansion included, mirrored switch `_ALIAS_SEED_EXPANSION`), `_write_target_entity_keys` (the walker's R29-U1 write-leg evidence read off the model's DML edges), `_field_part_match_ids` (the J12-9 owner-agnostic field-part predicate, one definition). Kept: alias-qualified seed copies (P1 MOVE→COPY), #399 alias-target seeds, R44 family-1 write-side copies (`bdm_acc_loan_info_sup@160`, `rrcdm_job_log_exec_par@213` on the flagship). Effect: seed-centering, the V2-N1 chip-visibility exemption and the Field Story's seed selection light only real seeds. Tests: `tests/test_target_scoping.py` (31 — FSB sweep, edges-unchanged pins, surviving multi-chip cases, ruling flagship), `test_l1_l2_integration.py::test_data_dt_seed_lands_on_searched_table` (restored ≥2-seed form, write targets only). Shift: 34/108 L2 snapshots change ONLY in `is_target` flags (0 structural); jaccard unchanged (18/20, the 2 ruled divergences). | ✅ |)
| R40.14 | **Self-loop chrome: caption retirement + border-scoring assignment (H4)** — (a) the `⟂ <fields> (filtered @L<line>)` caption was painted TWICE on one loop (the `FILTER_SELFLOOP_STYLES` edge-label rule AND the v3.3.190 caption node), and because the enlarged loop's midpoint sits OUTSIDE the table box neither copy was hidden by a node fill — `east5_stzfxxb.p_dt` showed two identical `⟂ p_dt (filtered @L190)` texts on one merged self-loop; (b) parallel loops on one table must not both bury themselves behind a neighbouring box | ✅ | (a) **v3.3.194 batch (landed, SHIPPED v3.3.195)** — the caption pass is RETIRED (user ruling 2026-08-31); `FILTER_CAPTION_STYLES` is an empty export still spread by `useCytoscapeGraph.js:267`; the loop line is now the loop's only on-canvas form and the absorbed line number travels through the R37 click→SQL channel and the Field Story "Filtered" step (`flowVisibility.js:128-151`, `graphStyles.js:1148`, the retired-preference note `flowVisibility.js:429-430`; pinned by `selfLoopFilterLabel.test.js:167-180`). (b) **border-scoring assignment (labelled v3.3.195 in the code comment)** — `borderScore()` (`flowVisibility.js:251`) counts, per side, the neighbour boxes overlapping the arc band plus the ordinary edges attaching there; `assignLoopSides` anchors the LABELLED loop on the freer border and lets the group share that border only when the opposite one is occupied; 3+ loops keep the v3.3.194 alternation as the greedy fallback (a deeper nest is a reach the two-band score cannot see). Loop placement is deterministic (highlight_line, then id — never payload order). *Audit percentages for (b) are transcript-only, no repo artifact.* |

## R40.13 — string-match diff layer + browse controls (solution & test plan, 2026-08-31)

User requirement (verbatim intent): *add a string-matching highlight in the SQL script panel plus
previous/next buttons in the Field Story bar to browse those highlights. Purpose: the user checks
the DIFFERENCE between naive string matching and the engine's search result. String matching is
CASE-INSENSITIVE.* Three user rulings froze the design; they are encoded below exactly and are
also the acceptance criteria in `requirements_v2.md`. This section is the design of record — it is
written BEFORE implementation (user-ordered) and the implementer should not have to make a
further decision.

### The seven frozen design points

1. **Color-coded diff.** Every naive-match line is styled by whether the ENGINE's flow closure
   covers it: covered = green band, not covered = the ruling's "amber/red" band (pinned to
   `--danger`/`--danger-soft` — see the CSS contract, ambiguity (b)). The Field Story bar shows
   the counter `N string matches · M in flow · K not in flow` (N = M + K).
2. **Always on after a search**, with a show/hide toggle in the Field Story bar. The engine's own
   highlight channel (`.edge-highlighted`, the R25/R37 single-line channel) is untouched and stays
   simultaneously visible.
3. **Naive baseline**: case-insensitive, word-boundary matches of the field name over the WHOLE
   script — comment lines and string-literal lines included. That inclusion is the point: the
   layer is the "what would a dumb grep see" baseline, not a semantic opinion.
4. **Prev/Next browse** the match lines (sorted ascending) by scrolling the SQL panel and putting
   an "active" outline on that line, through a SEPARATE cursor state — never the R37
   `sqlHighlightLine` channel. Browsing must not clobber the engine's line.
5. **Pure client-side**: no backend change, no API, no cache key, no snapshot change, no
   `EXTRACTOR_VERSION` bump. Works in both the flow-only and the full L2 view (and their merged
   variants); the coverage baseline is always the FLOW closure's highlight set — the engine's
   claim — independent of the view toggle.
6. **Boundary rule**: custom lookarounds, not `\b` — see the verification below.
7. **Edge cases**: no active search → layer hidden; 0 matches → the counter reads
   "0 string matches"; the chip's own definition line is a legitimate match (the baseline is naive
   — it WILL match the birth line; that is correct and the covered/missed coloring still applies).

### Boundary rule — exact rule and verification (design point 6)

Exact rule (frozen): case-insensitive match of the ESCAPED field name with custom lookarounds —

```js
// frontend/src/utils/stringMatch.js
const escapeRegExp = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Boundary = "not an identifier character". The class is [A-Za-z0-9_$] — the frozen
// ruling's class, verbatim. Flags are "i" ONLY: a "g" flag makes .test() stateful
// (lastIndex advances across calls) and silently skips lines.
export const buildBoundaryRegex = (name) =>
  new RegExp(`(?<![A-Za-z0-9_$])${escapeRegExp(name)}(?![A-Za-z0-9_$])`, "i");
```

Verified against the frozen intent, with evidence:

| Probe | lookaround (frozen) | `\b` | Why |
|-------|---------------------|------|-----|
| `p_dt2` searching `p_dt` | no match | **no match** | trailing digits are regex word chars, so `\b` rejects them too |
| `p_dt_backup` searching `p_dt` | no match | no match | same |
| `p_dt$x` searching `p_dt` | no match | **MATCHES (wrong)** | `$` is an identifier character in Hive/ODPS but a regex NON-word char, so `\b` claims a boundary between `t` and `$` |
| `x$p_dt` searching `p_dt` | no match | **MATCHES (wrong)** | same, leading side |
| `p_dt#x` searching `p_dt` | matches | matches | `#` is NOT in the frozen class (see the ambiguity note below) |

So the documented rationale is precise: **`\b` is wrong because `$` is an identifier character
while `\w` is `[A-Za-z0-9_]`** — the lookaround class is `\w` plus `$`, on BOTH sides. The
"would match `p_dt2` for `p_dt`" failure mode in the ruling text is the failure mode of the
*no-boundary substring* baseline, not of `\b`; `\b` and the lookaround agree on trailing digits.
The rule's job is to keep the naive baseline from degenerating into substring matching, and the
lookaround form (not `\b`) is what keeps `$`-containing identifiers one token.

*Ambiguity resolved here, flagged for the implementer:* the ruling's prose motivates the rule with
"`$`/`#`-containing Hive/ODPS identifiers" but the frozen regex class covers `$` only. **Encode the
frozen class exactly** (`[A-Za-z0-9_$]`); `#` is therefore a boundary character and `p_dt#x`
matches `p_dt`. Measured: 0 `$`- or `#`-joined identifiers across the whole `samples/` corpus, so
the omission has zero effect today. If a future corpus introduces `#`-identifiers, that is a
one-character class amendment (`[A-Za-z0-9_$#]`) and needs a new user ruling — do not change it
silently.

### Solution sketch (design of record)

| File | Addition |
|------|----------|
| `frontend/src/utils/stringMatch.js` (NEW, pure, no React) | `computeStringMatches(sqlText, fieldName) → [{ line, text }]` — 1-based `line`, ascending, one entry per matching LINE (a line with 3 occurrences is ONE entry); `classifyMatches(matches, flowLines) → { covered, missed }` where `flowLines` is the `flowLineSet()` baseline (a `Set<int>`; any iterable of integers is accepted) and the two results are DISJOINT ascending arrays of line numbers; `buildBoundaryRegex(name)`; `flowLineSet(l2Result) → Set<int>` (the baseline, below). No sqlglot, no parsing — `sqlText.split("\n")` + the boundary regex |
| `frontend/src/components/SqlPanel.jsx` | Three new OPTIONAL props: `stringMatchCovered` (`Set<int>`), `stringMatchMissed` (`Set<int>`, disjoint from the covered set by construction) and `stringMatchActiveLine` (`number \| null`). Absent/empty sets → the layer renders nothing. Per-line classes become `sql-line` + `edge-highlighted` (unchanged engine channel) + `string-match covered` / `string-match missed` (layer) + `string-match-active` (cursor). Band = whole-line background tint + 3px RIGHT border; NO per-token inline markup — the `.line-text` span stays a plain string, so the diff layer never touches text rendering or the export path |
| `frontend/src/components/FieldStoryBar.jsx` | New cluster: a show/hide toggle, the counter, and `◀ 3/17 ▶`. New optional props: `stringMatchSummary` (`{ total, inFlow, notInFlow } \| null` — non-null whenever an L2 search is active, INCLUDING `total: 0`; `null` = no active search, so the cluster does not render at all), `stringMatchCursor` (`number \| null`, 0-based), `stringMatchVisible` (bool), and callbacks `onToggleStringMatch`, `onPrevStringMatch`, `onNextStringMatch`. Everything stays presentational — ALL state lives in DataFlowApp (the R40.3 convention) |
| `frontend/src/DataFlowApp.jsx` | `flowLines` memo (`flowLineSet(l2Result)`) + `stringMatches` memo (`computeStringMatches(sqlText, activeView?.field)` — the canonical field name, canonical already post-R2.11) + the covered/missed split memo (`classifyMatches`); `stringMatchCursor` + `stringMatchVisible` state (default `true`); the ◀/▶ handlers set the cursor (and the panel scrolls through the prop); reset rules below |
| `frontend/src/styles/app.css` | `.sql-line.string-match-covered`, `.sql-line.string-match-missed`, `.sql-line.string-match-active` — declared AFTER `.sql-line.edge-highlighted` (app.css ~L474) so the later rule wins the background |

**Coverage baseline (design point 5) — the exact payload read.** Compute from the CURRENT L2
search payload, in the DETAILED namespace, never the merged projection:

```
flowLines =
  { e.data.highlight_line for e in l2Result.graph.edges
      where e.data.id ∈ l2Result.flow_edge_ids and highlight_line is an integer ≥ 1 }
  ∪
  { n.data.line_start    for n in l2Result.graph.nodes
      where n.data.id ∈ l2Result.flow_node_ids and line_start is an integer ≥ 1 }
```

`l2Result.graph` is the detailed graph (the namespace `flow_node_ids`/`flow_edge_ids` are keyed
in); `full_graph`/`l2m_*` is the merged projection of the SAME closure — never read it here, which
is what makes the baseline independent of the flow-only/full/merged toggle. If the flow sets are
absent or empty (the not-in-flow response, `search_matched: false`) the baseline is EMPTY and
every naive match classifies as not-in-flow — that is the truthful reading ("the engine claims
nothing on this script"), not a defect. Guards are the standard INV-2 guard (integer ≥ 1, else
skip — never guess a line).

**Scroll channel — decision recorded.** The cursor scrolls the panel through the NEW declarative
prop `stringMatchActiveLine` with its own `useEffect` in `SqlPanel` (same shape as the existing
`sqlHighlightLine` effect: scroll only when the value changes, `scrollToLine(line)`, integer ≥ 1
guard). A ref-based `scrollToLine()` call was rejected: `DataFlowApp` holds no `SqlPanel` ref
today, and the declarative prop mirrors the existing engine channel, stays testable in vitest
without refs, and keeps the two channels independent. The two effects do not cancel each other —
whichever changed last scrolls last.

**CSS contract.** The three channels compose and never overwrite each other's markers:
`.edge-highlighted` keeps its amber background + 3px LEFT border; the layer adds a background tint
+ 3px RIGHT border (`covered`: `var(--success-soft)` / `var(--success)`; `missed`:
`var(--danger-soft)` / `var(--danger)`); `.string-match-active` adds
`outline: 2px solid var(--accent); outline-offset: -2px` (an outline, so it never shifts layout
and reads over either band). When a line is both an engine anchor and a naive match (east5 L41 and
L190) the layer's tint wins the background and the engine's amber left bar stays legible — that is
how "untouched and simultaneously visible" is honored. `--danger` is used for "not in flow" rather
than the engine's `--warning` amber so the three meanings keep one token each: amber = the engine
anchors here, green = naive match the engine covers, red = naive match the engine does not.

**State and interaction rules.**

- Visibility: default `true` on every new search. The toggle flips the band/outline classes only;
  the counter STAYS visible while hidden (it is the diff summary the feature exists to show), and
  ◀/▶ are DISABLED while hidden. Toggling does not reset the cursor.
- Cursor: `null` = inactive (no active line, no extra scroll — the layer's bands alone are the
  post-search state, so browsing never fights the engine's own post-search scroll). `▶` from
  `null` activates index 0; `◀` from `null` activates the last index (the controls wrap).
  Otherwise `±1` with wraparound modulo N (`(i + 1) % N`, `(i - 1 + N) % N`) — the browse list is
  a ring, deliberately unlike the story steps, which clamp and never wrap (R40.3).
- Readout: `◀ 3/17 ▶` = 1-based cursor position / total; `–/17` while inactive. The counter is the
  separate `N string matches · M in flow · K not in flow` string. At N = 0 the counter reads
  "0 string matches" (the M/K suffix is omitted), there is nothing to browse, and the layer has no
  bands — but the bar and the counter still render.
- Reset: null the cursor whenever the match set's identity changes — (`scriptName`, `fieldName`,
  `sqlText`) — and clamp instead of guessing if `cursor ≥ N` after a payload change.
- Render gate: the Field Story bar currently renders only when
  `fieldStory && fieldStory.steps.length > 0`. That gate WIDENS to
  `steps.length > 0 || stringMatchSummary != null`, so the browse controls exist whenever a search
  is active even if the script has no story steps; the story chip row + autoplay render only when
  steps exist, the string-match cluster only when a search is active (`stringMatchSummary != null`
  includes `total: 0` — a 0-match search still renders the bar and the counter, per design
  point 7). The badge label stays "Field story".
- Layer requires: `graphLevel === 'L2'` (the SQL panel only mounts in L2), a non-empty canonical
  field name, and non-empty `sqlText`. Any of these unmet ⇒ `computeStringMatches` returns `[]`
  ⇒ the layer is hidden (design point 7). "Both views" (design point 5) = the L2 flow-only /
  full toggle and their merged variants — there is no L1 SQL panel to style.

**Ambiguities resolved here (implementer: these are decisions, not open questions).** (a) The
`#` boundary question above. (b) "amber/red band" is pinned to `--danger`/`--danger-soft` so the
engine's amber stays unique. (c) The counter remains visible while the layer is hidden. (d) The
browse cursor wraps; the story cursor does not. (e) The bar's render gate widens as above. (f) The
cursor is NOT auto-activated on a new search. (g) The scroll channel is the declarative prop, not
a ref call.

### Test plan (implementation team executes)

**Unit — `frontend/src/utils/__tests__/stringMatch.test.js` (new, pure util).**
Boundary: `p_dt` does not match `p_dt2` / `p_dt_backup`; `p_dt` does not match inside `p_dt$x` or
`x$p_dt`; case-insensitivity (`P_DT`, `p_Dt`, `p_dt` all match); escaping (`count(*)`-shaped and
regex-metacharacter field names do not throw and match literally); `\b` parity probe on trailing
digits (documents the ruling correction). Baseline: comment lines (`-- p_dt …`) and string-literal
lines (`WHERE x = 'p_dt'`) are INCLUDED; the chip's own definition line is included; `0` matches
→ `[]`; empty/whitespace field name → `[]`; `null` sqlText → `[]`; a multi-occurrence line yields
one entry. Classification: `classifyMatches` vs a fixture `flowLines` set — covered/missed
partition correctly, an empty set classifies everything as missed, non-integer/0 lines in the
baseline are dropped, both outputs ascending.

**Component — extend `frontend/src/components/__tests__/SqlPanel.test.jsx` and
`frontend/src/utils/__tests__/fieldStoryBar.test.jsx`.**
SqlPanel: a line in `stringMatchCovered` renders `string-match covered`, a line in
`stringMatchMissed` renders `string-match missed`; a line in neither set renders no band; the
engine channel still renders
`edge-highlighted` on its own line and BOTH classes coexist on a shared line (the L41/L190 shape);
`string-match-active` lands on exactly one line; `stringMatchActiveLine` changes scroll the panel
(scrollIntoView called) WITHOUT changing `edge-highlighted`; absent props render nothing extra
(backwards compatible).
FieldStoryBar: the counter renders `N string matches · M in flow · K not in flow`; `0` matches
renders "0 string matches" with both buttons disabled; the `3/17` readout tracks the cursor and
shows `–/17` when inactive; ◀/▶ callbacks fire with the right indices (start-at-0 from null, last
from null on ◀) and wraparound fires at both ends; the toggle callback fires and, when hidden, the
buttons are disabled while the counter is still rendered; the story chips and the string-match
cluster render independently of each other.

**App wiring (the cursor/scroll/reset rules above) — covered by the component tests + a manual
pass; no new React-testing-library harness is introduced for DataFlowApp.**

**E2E (manual / E2E team) — `east5_stzfxxb.p_dt`, script `EAST5_STZFXXB_M.sql`.** Expected
fixture, derived from the engine's committed closure (`backend/tests/snapshots/
l2_snapshot_04_EAST5_STZFXXB_M.sql.json`: 5 nodes / 7 edges, `search_matched` true) and the naive
scan over the sample: closure lines {41, 179, 189, 190}; 12 naive match lines; counter exactly
"12 string matches · 2 in flow · 10 not in flow". L41 (the INSERT OVERWRITE … PARTITION line) and
L190 (`WHERE p_dt = …`) are green AND carry the engine's amber left bar when either is the current
R37 highlight; L166–175 (the ten `ALTER TABLE … ADD PARTITION` lines) are red — precisely the R43
"folder names, not dataflow" exclusion, which is the difference this feature exists to show; the
engine's L179/L189 anchors carry NO band (they are not naive matches — the engine sees the flow
through `rrcdm_job_log_exec_par`, the naive scan cannot). Also verify: flow-only ↔ full and
merged toggles leave the bands and the counter IDENTICAL; stepping the browse controls never moves
the engine's `edge-highlighted` line; a fresh search resets the cursor and re-counts.

> Related note for the test team, no action in this feature: `backend/tests/
> test_flow_line_invariants.py` scans the fixture for field lines with `\b…\b`. That is a
> test-internal scan, not shipped code, and it agrees with the lookaround on this fixture —
> the frozen lookaround is the RULE for the shipped layer.

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
| R42.4 | **M-E1**: merged vs detailed L2 views share one layout-persistence key — a drag in one view pinned positions in the other. **AMENDED 2026-09-02 (R53): only the merged flow-only key is user-reachable today; the detailed/`full-merged` keying stays in the code, CUT** | ✅ | Split by view family: merged views (`flow-merged`/`full-merged`) persist under `l2:merged:{script}`, detailed views keep `l2:{script}`. Implemented at BOTH the save path (`scheduleLayoutSave` script key) and the read path (`savedPositions`) in `DataFlowApp.jsx`; `layoutPersistence.resumeLayoutKey` unchanged (`resumeLayoutKey('l2','merged:X') → 'l2:merged:X'` composes exactly); backend unchanged — `save_layout` treats the script value as a free-form key (`f"l2:{script}"`, no script-name validation). The split is kept verbatim so a revived Full/detailed view resumes correctly on day one |
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
| R43.4 | Costs | ✅ | Snapshot regeneration PENDING — `tests/test_l2_snapshot.py` (l2_snapshot_02 pins pre-R43 EAST5 full-graph counts) is EXPECTED TO FAIL until the orchestrator's unified regeneration (a parallel team owns the snapshots right now; not rebaselined here). `total_nodes` in the level2 response drops by the dropped raw nodes on the full view (display-only; no consumer pins it). **2026-08-29 note:** the red set is EXPECTED TO GROW (≈46 → ≈75 snapshots) until the unified rebaseline runs — drivers: R44's occurrence twins (incl. R45 family 3), the F-B1 chip `line_start` keys, the K3 sample repairs, the filter-operand twins (R44.4) — see the DRAFT/PENDING entry in `SNAPSHOT_CHANGELOG.md`. Snapshot failures before that point are expected rebaselines, NOT regressions. **CLOSED 2026-09-01** — the unified regeneration ran at the v3.3.195 release gate (commit `3777e9e`): the expected-red window is over, the 108 committed baselines are the shipped truth and the gate is green |

## R44 — Walker occurrence coverage (user ruling, 2026-08-28) — ✅ LANDED + SHIPPED v3.3.195 (R45 family 3 included)

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
| R44.2 | Benchmark re-derivation follows the new walker | ✅ | ground truth is re-derived independently (never from the system's own output); the gate stays set-equality (recall AND precision both 1.0), not a size check. IN FLIGHT: the PL stray-`;` repair (R13.7) moves 3 canonical rows and those are being re-pinned. **CLOSED 2026-09-01 — §R46**: R46c/R46d re-derived the canonical FROM THE SQL TEXT (86 rows removed with ruling citations + the 30 nodes they fed, R46d's twin rows added under the inert `e5tw` key); the gate is **20/20 at 1.0000/1.0000 recall AND precision** |
| R44.3 | Unified snapshot regeneration lands with R44 | ✅ | all L2 snapshots regenerate once at the next release (R43 DDL-drop + RFN #370 + R44 twins + the chip `line_start` keys + the K3 sample repairs together) — see R43.4 and the DRAFT entry in `SNAPSHOT_CHANGELOG.md`; snapshot failures before then are expected, not regressions. **CLOSED at the v3.3.195 release gate** — the unified regeneration ran (commit `3777e9e`): **108 committed baselines, all green**; the `SNAPSHOT_CHANGELOG.md` PENDING entry is closed |
| R44.4 | **Filter-operand twin edges (F-E1, 2026-08-29 simulation finding)** — the seed's occurrence inside a filter's operand expression carries its own edge, so the operand line is reachable and the merged view can anchor it | ✅ | **LANDED — verified in the shipped tree 2026-09-01 (doc-hygiene sweep)**. Engine: Phase 6 admits the occurrence twin whose GROUP (same context + casefolded `owner.field`, never a bare-column match) collected a filter clause — `_twin_group_admits` + `_FILTER_CLAUSES` at `dependency_graph.py:979-1035` (`_twin_group_admits(v, _FILTER_CLAUSES)` at `:1033-1035`, the JOIN clause at `:1059`); the extractor hands each twin its group's clause multiset (`variable_extractor_v2.py:624`, `:2600-2607`), and `l2_builder.py:2476` documents the R45 Fix B / F-E1 walk order that makes the group pairing necessary. So a `AND podtao <> pofddt` / `p_dt <= TO_DATE(...)` predicate line carries its own FILTER edge and reaches the flow closure. Tests: `backend/tests/test_filter_twin_edges.py` (committed, clean) — `TestSupMPredicateTwins::test_predicate_line_twins_carry_own_line_filter_edge` and `::test_predicate_lines_reach_the_l2_flow_closure`, `TestRfnMaxPdtSubquery::test_pdt_predicate_occurrences_carry_own_line_edges`, `TestTwinGroupOwnerGuard::test_clause_never_borrows_across_owners` + `::test_no_cross_owner_group_anywhere_in_the_corpus` |

## R46 — Canonical ground-truth re-derivation (R46c/R46d, 2026-09-01) — ✅ DONE (the jaccard gate is 20/20 at 1.0000/1.0000 recall AND precision)

Amends the CR10 requirement ("ground truth MUST be built by a different/independent method — never
from the system's own output") and closes R48.5 and R44.2. The v3.3.195 wave changed the served
closure three times over (R46c's `_value_cone_gate`, J1's field-involvement rule, R46d's
continuation twins), so the canonical rows for the affected seeds were **re-derived FROM THE SQL
TEXT row by row** — never reconciled with what the engine now emits — and the rows the text refutes
were REMOVED with the ruling citation. Status notes live in
`backend/tests/jaccard_canonical.py` (points 20–25); the OLD canonical remains in git history.

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| R46.1 | The canonical is re-derived from the SQL text, not from the engine's output | ✅ | R46c (point 20) removed **86 rows + the 30 canonical nodes the dropped chips fed (24 `lending_ref` + 6 `iiapty`)**: 75 `lending_ref↓SUP_M`, 10 `iiapty↓SUP_M` (IID8/IID10/IID12–IID17/IA1/IA2), 1 `lending_ref↑DL` (LFD2). Every removed row carries an inline `REMOVED (R46c … class Xn)` marker at its old site |
| R46.2 | The removal classes are cited, each verified against the script text | ✅ | **X1** sibling join-key operand legs (61 — the CONCAT/RPAD concatenation keys put the searched field on ONE side of the `=`), **X2** sibling-field predicates (4), **X4** the rrcdm job-log trunk (4 — a bare `TOP{n}` context is not a scope, so W6b cannot justify a top-level trunk; reverses the R29 row-level continuation pins of 2026-08-12), **X5** a JOIN anchored at a SELECT-projection line (LFS41/LFS123/LFD2 — the LFS123 doctrine, now enforced by J1 Class 1), **X6** sibling write-zone legs / box legs with no field evidence (14) |
| R46.3 | R46d: every occurrence twin carries its OWN canonical row (no fold-through) | ✅ | V5's `EXTRACTOR_VERSION 2026-08-28.12` (dependency_graph Phase 9 + the family-4 JOIN-ON AND legs) mints each arm's own flow edge; the twin rows live under the `e5tw` seed key, **INERT IN THE GATE by construction** (no `CASES` entry selects `e5tw` — adding one needs a `CASES` + `FLOORS` pair). The arms' `_value` TABLE_FLOW write legs are deliberately NOT pinned (they would assert the output projection twice) |
| R46.4 | Set equality, both directions, every case | ✅ | measured on the v3.3.195 tree: `lending_ref↓SUP_M` 21 nodes / 66 edges / 27 highlights, `iiapty↓SUP_M` 7 / 9 / 5, `lending_ref↑DL` 6 / 9 / 3 — all 1.0000/1.0000; the whole gate **20/20 at N=E=H 1.0000/1.0000**. Point 25's audit adds the structural checks: no duplicate row (the one twice-asserted identity, LFS117/LFS138, is the RULED G9 instance-identity rendering), no unconsumed served edge, no unrealized canonical node |
| R46.5 | The CR10 "pending" ledger is closed | ✅ | point 24: every row whose form was an engine-emission convention is re-derived from the SQL text and its flag cleared (output-VT membership, LFD2, LFD3, IID3, IID6, IID8/LFS68); the flag MACHINERY stays for any future engine-form row. The consumer test prints no PENDING line |
| R46.6 | The two ruled-red `lending_ref` benchmark cases are GREEN again | ✅ | the benchmark deselects were retired from `release.sh` (commit `0ac1c81`). **Residual, deliberately NOT absorbed into B** (CR10: never copy engine output as truth): `sup↓SUP_M` prints 14/15 edges and `pl↓PL` 8/9 N / 9/11 E / 5/6 H until the engine owner repairs the R46d family-4 emissions (point 23 — measured invariant to the gate AND to the fold, so the cause is the leg pass, not the gate) |

## R48 — Field-involvement admission (USER RULING, 2026-08-31) — ✅ LANDED + RESOLVED (fix team J1; the benchmark divergence was closed by the R46c canonical re-derivation, §R46)

User ruling: **"only edges where the searched field is involved in the data flow are shown."**
Applied to the 6 over-included engine edges the G9 cross-check ledgered on `lending_ref↓SUP_M`
(2 mis-anchored JOINs + 4 sibling-field value legs).

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| R48.1 | Class 1 — a JOIN carrier is served only at a JOIN-ON line (the projection/read-line inheritance is gone) | ✅ | `l2_builder._apply_field_involvement` Class 1 + `dependency_graph.line_clause_map` (the extractor's own `_line_clauses` machinery: same tokenizer, same `_LINE_CLAUSE_TOKENS`). SUP_M × lending_ref: the L82 (CASE read) and L163 (write projection) JOIN carriers are no longer served; the real sites L41/L95/L117/L150/L156(×2)/L201 all stay. RFN × repay_acct_no: 7 crossed JOIN carriers dropped at L500/630/936/951/1095/1178 — all SELECT-list lines, verified in the script text |
| R48.2 | Class 2 — a sibling field's value legs are not this seed's flow (write value leg, ⟐output membership, write-projection read leg, output-frame chain) | ✅ | the 4 ledgered `reserved_field8` legs (l2e_43563f4fce74 / l2e_3e806f355c16_value / l2e_95a6f49b4f2e / l2e_1eb5aca70da6) are gone; the sibling's belongs-to SCHEMA (LFS135/LFS143-145 class), ALIAS hops, CTE chains and the searched field's own everything stay. Same class removed on 6 more cross-check cases (PL product 2, DL acnw 7, RFN reserved_field9 44, RFN repay_acct_no 28, SUP_M abnormal_issue_flag 1, EAST5 stzfdxhh/reserved_8 15 each) |
| R48.3 | Display-only: the walker's NODE closure and occurrence coverage are untouched | ✅ | 14-case before/after spot check (the 11 G9 cross-check cases + 3 simple EAST5 fields): node sets byte-identical, naive string-match coverage identical in every case (0 lines lost), served edges 147→139 (SUP_M lending_ref) |
| R48.4 | Field Story does not regress — it may only lose WRONG steps | ✅ | lending_ref SUP_M story: 15 → 14 steps, the removed step is exactly `joined@67` (the mis-anchored carrier); the R40.12 flagship `reappears@59` and every other step stay. EAST5: `p_dt` 3/3 identical (birth-41/written-41/filtered-190 — the G6 canonical), `stzfdxhh` 4/4, `CHARGE_DEPARTMENT` 3/3 |
| R48.5 | Benchmark divergence (the rule is the authority; the user rules on the ground truth) | ✅ **RESOLVED** | 18 of 20 benchmark cases stay 1.0000/1.0000. Three canonical rows are RULE-VS-CANONICAL CONFLICTS — the served view drops them: `LFS41` + `LFS123` (JOIN carriers anchored at L67, a projection line; the canonical's own LFS123 note concedes "no join happens there") → `lending_ref↓SUP_M` E 0.9858/1.0000, and `LFD2` (the upstream FROM-source JOIN@101, already CR10-"pending") → `lending_ref↑DL` 0.9000/1.0000. `tests/jaccard_canonical.py` deliberately left untouched. **RESOLVED 2026-09-01 — see §R46**: the canonical was RE-DERIVED from the SQL text (R46c, user-approved) and all three rows are REMOVED with the ruling citation (class X5 — a JOIN anchored at a SELECT-projection line is not the relationship's own site); the old canonical rows remain in git history. Both cases are GREEN again — the gate is **20/20 at 1.0000/1.0000 recall AND precision**, and the two ruled-red benchmark deselects were retired from `release.sh` (commit `0ac1c81`) |
| R48.6 | Tests | ✅ | `tests/test_field_involvement_rule.py` (12: the 6 drops per class, the kept set, real-join-site survival, node-set invariance, surgical-change property on a simple closure, determinism, full-view no-op, the predicate's per-class decisions, the no-model safety direction). Gates: `test_l2_combine_edges` + `test_g8_multi_anchor` + `test_g7_rc_c_fixes` + `test_l2_line_merged_benchmark` + `test_mech_payload` + `test_l1_l2_integration` all green |

## R49 — L2 snapshot integrity: the physical model is persisted with the graph cache (FSC-2, v3.3.195 wave, fix team V6) — ✅ LANDED

FSC's structural hole (b) — "the closure is not a pure function of the script" — as a requirement:
**the L2 answer a workspace serves for a given SQL text must be the same answer whichever cache
survived.** Before this landed it was not: the physical model the strict table.field walker
consumes was built from the analysis dict when an analysis cache was present (the `alias_of`
extraction truth) but from the cached GRAPH JSON when it was not, and the graph cache serialises
nodes without `alias_of`, so the second form fell back to `physical_model`'s label-keyed alias
rule. Measured on RFN: **28 of 74 `alias_by_var_id` pairs** differ between the two input forms
(var `15b561ec4099c7c3` → `bdm_acc_loan_info` from the truth vs `ODS_IFAI_FCLETWK` from the
guess); SUP_M 4 of 14.

Fix = **persistence, not a smarter fallback**: `cache/model_{cache_key}.json`
(`graph_service.MODEL_CACHE_PREFIX = "model"`, its own `MODEL_CACHE_FORMAT_VERSION = 1`) is
written by every build from the SAME analysis the graph was built from, and read by every
graph-cache hit that cannot rebuild the model from an analysis cache. Every guard failure returns
`{}`, which the callers treat as "no persisted truth" → the pre-FSC-2 label-rule fallback — a
stale artifact can never poison a model, it can only be ignored.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R49.1 | The persisted-truth model is byte-identical to the analysis-path model — the whole `PhysicalModel` deep-equal (alias map, entity map, table names/roles/alias views, field occurrences, edges, occurrence index) | ✅ | `graph_service.py:374-478` (`extract_alias_of` / `write_model_cache` / `load_model_cache` / `graph_with_alias_of` — the last makes SHALLOW node copies and never mutates the served payload); `l2_builder.py:240-266` + `dataflow_service.py:567-584` (the read ladder: analysis cache → persisted alias truth → cached graph); `l2_builder.py:314-321` + `dataflow_service.py:634-641` (the write, even for an alias-free script — the file's PRESENCE is what says "this graph cache carries its truth"). Tests `backend/tests/test_model_persistence.py:241,279` (12 tests, suite green) |
| R49.2 | The served response is byte-identical across cache paths and independent of the caches' creation history | ✅ | `test_model_persistence.py:333` (RFN + SUP_M + PL + EAST5, through the committed snapshot seeds), `:355`; cross-seed stable PYTHONHASHSEED 0–3 (`:510`) |
| R49.3 | The user-visible defect is gone: an alias-qualified seed gets its closure, not the whole graph | ✅ | the lossy variant left no seed (the seed expansion consumes `alias_by_var_id`) → `search_matched: false` + the FULL graph. Pre-FSC-2: RFN `a.cust_no` served 1053 nodes / 6764 edges instead of the **78-node / 221-edge** closure; SUP_M `p3.lending_ref` 219/679 instead of 9/13. Both spellings (`a`/`A`) pinned — `test_model_persistence.py:390-411,403` |
| R49.4 | Old caches keep working (no hard break) and the artifact cannot serve stale data | ✅ | a graph cache without a sibling artifact keeps the pre-FSC-2 behaviour and the lossy result is the documented one (`:549`, `:602`); `purge_workspace_caches` deliberately does NOT delete `model_*.json` — the reader requires contract version + extractor version + cache_key to match, so keeping it buys no staleness risk while purging it would reintroduce the hole (`main.py:74-81,101-102`; `:634`, `:669`) |
| R49.5 | Cache invalidation contract | ✅ | NO `GRAPH_CACHE_PREFIX` bump needed: the artifact carries its own `format_version` + `extractor_version` + `cache_key`, so an engine change invalidates the model read without invalidating the graph caches; the graph cache keeps its own C9/Round-12 guards |

## R50 — MERGE/predicate-clause column connectivity (H11, Phase 4d-gc) — ✅ LANDED

The 7 DEFECT-class `column_connectivity` findings R4-H's waiver tightening handed back: a MERGE
statement's column (walked by `_walk_merge` through `ON` / `UPDATE SET` / `WHEN`, or by
`_walk_join` through an ordinary JOIN ON) resolves I2 to the USING/derived alias's PHYSICAL table
and R44's family-2 twin registers it under the owner-qualified spelling `{owner}.{col}`. Its
qualifier IS the physical owner, so Pass 4a skips it (the owner is the original name), Phase 4d's
prefix match misses it, and Phase 4d-gb's gate enumerates only `GROUP BY` + the OCCURRENCE marker
— the MERGE/JOIN-ON clauses fell between the two and the variable carried **no incoming SCHEMA
edge at all**.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R50.1 | Every MERGE/predicate-clause column of a physical owner carries that owner's belongs-to SCHEMA edge | ✅ | `dependency_graph.py:113-116` (`_MERGE_COLUMN_CLAUSES` = {MERGE ON, MERGE UPDATE SET, MERGE WHEN, MERGE INSERT, JOIN ON} — the gate is pinned by test, `MERGE`/`MERGE USING` never admit a column), `:118` (`_statement_scope`), `:829-905` (Phase 4d-gc). **Blast radius measured: exactly 7 new edges corpus-wide** — the probe diffs the build with the clause set emptied over every sample + `financial/fin_query*.sql` and asserts 7 (`tests/test_merge_connectivity.py:244-291`) |
| R50.2 | The admission can never fabricate a schema fact | ✅ | admission needs the model's OWN schema evidence: a QUALIFIED read that I2 resolved to `owner` in the SAME statement; the witness is owner-scoped and NEVER owner-spelled (an `{owner}.{col}` var's spelling proves nothing — it is the shape under adjudication), so the rule cannot witness itself. That is exactly what separates the 7 defects from the same clause family's false positives (fin_query4's `gps_transactions.account_id` is the twin of a RENAMED USING projection, `t.source_account_id AS account_id` @8 — no alias-spelled read of it exists in the statement, so the belongs-to premise is false) |
| R50.3 | The waiver ledger reconciles with the fix | ✅ | the 7 DEFECT entries are REMOVED from `test_graph_integrity.py::_ADJUDICATED_CONNECTIVITY`; the 7 FALSE POSITIVE entries STAY and must keep firing (`:167-232`: fin_query4 ×1, fin_query8 ×2, fin_query14 ×4). `tests/test_merge_connectivity.py` — **35 passed**, each defect asserted to have stopped tripping |
| R50.4 | The display fold that surfaced the missing anchors is itself fixed (RC-B, fix team G8) | ✅ | `_combine_edges` keyed (source, target, edge_type) and kept ONE carrier per pair, so N occurrences of the searched field reaching the same target rendered one anchor and went dark on N−1 — the model carried the per-occurrence edges the whole time. Fold key = (source, target, edge_type, ANCHOR) with ANCHOR = the `highlight_line` the carrier will be served with; K anchors ⇒ K served edges, ascending. Evidence: SUP_M lending_ref served at L201 only while the model held JOIN edges at L95/L156/L163/L206 — `tests/test_g8_multi_anchor.py` (6) |

## R51 — The container-PROVENANCE bridge is deterministic and is KEPT (X1 relay, v3.3.195 wave) — ✅ LANDED

Phase 3's container bridge (G7 RC-C, `EXTRACTOR_VERSION 2026-08-28.10`) wires a container body
(CTE / SUBQUERY / VIRTUAL_TABLE) that produces a value to the outside reader that consumes it —
the seam where every container chain was value-disconnected. X1 re-reviewed the phase.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R51.1 | The picked producer — and with it the served L2 edge id — must not depend on the interpreter's string hash | ✅ | the candidate containers lived in a `set`, so `producers[-1]` inherited hash order: **7 distinct PROVENANCE pick-sets on RFN across 8 PYTHONHASHSEEDs, 2 on SUP_M**. The candidate list is now built ONCE and put in a TOTAL ORDER `(line_start, var_order[id])` — process-independent AND the D3 last-writer-wins the comment always claimed. `dependency_graph.py:630-646`; `tests/test_dependency_graph.py::TestProvenancePhase` (the two-source `d1` fixture that flips pre-fix; the hash varied in a CHILD process, the only honest way) |
| R51.2 | The bridge must not close a 2-cycle on a pair it did not create | ✅ | guard 3 only saw edges INTO the reader, so an existing reader → producer REF/TRANSFORM leg coexisted with the new producer → reader PROVENANCE leg — **14 direct 2-cycles corpus-wide (7 SUP_M, 7 RFN; 5 materialized as SUP_M display edges)**. Guard 3b refuses a producer → reader leg when the reader → producer leg already exists. `dependency_graph.py:663-671` |
| R51.3 | The phase is KEPT (the strip-measurement that argued against it is obsolete) | ✅ | X1's earlier strip-measurement predated the J12-10 walker that consumes PROVENANCE edges, so it measured a different engine: stripping today loses **47–80 lit lines per search** on the flagship searches (working-session measurement, no repo artifact). Direction stays value direction (producer → reader), op `PROVENANCE`; `lineage` admits its forward half unconditionally and gates only the reverse half on the searched field — a plain REFERENCE edge here would be walked BOTH ways and fan the container's column out to every same-named var (measured 16 → 267 nodes on RFN `reserved_field9`). `lineage.py:1203-1219` (the X1 comment correction: the old comment's "consumer to producer" was inverted relative to the stored source/target order) |
| R51.4 | The flagship's served edge count is pinned and witness-checked | ✅ | RC-B's multi-anchor fold moved it 528 → 673/674 (the flap was the pre-existing graph_service cross-process leak — for ~10 REF edges the same logical edge was minted from a DIFFERENT duplicate raw node id per PYTHONHASHSEED, invisible under the single-carrier fold); R51.1+R51.2 removed the hash-order source of most of it and dropped the 14 2-cycles → **stable 668 across PYTHONHASHSEED 0–3**, lit-line sets and flow closures byte-identical on all 7 flagship searches (R46d then moved it 668 → 669: one FILTER@182 row-selection edge, SQL-text-verified). `tests/test_physical_model_equivalence.py:323-359` (the count assert + the witness loop) |

## R52 — M-T1: TVF alias definition lines (fix team, v3.3.195 wave) — ✅ LANDED

A table-function alias was registered through the ordinary `_register_table` alias branch, but its
I1 def-site run `[name, alias]` is never ADJACENT for a TVF — the call's parenthesized argument
list sits between the function-name token and the alias token (`name ( args ) alias`) — and the
run matcher's strict branch only skipped STRING and AS tokens, so it aborted on the `(` and both
the statement-scoped pass and the whole-stream fallback returned 0. The alias anchored L0, so
clicking it silently no-op'd (R37.3's guard) and every edge riding it highlighted nothing.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R52.1 | A TVF alias anchors on its own call line, never L0 | ✅ | opt-in `skip_parens` on the run matcher — ONE balanced parenthesized group may stand between two run tokens, bounded by the statement range, an UNTERMINATED group failing the candidate (never invents a line). Only the TVF alias's def site passes it (6-tuple def_site); every other variable keeps the exact run forms it had. `variable_extractor_v2.py:265-283` (changelog), `:1641-1702`, `:1936-2035`; `EXTRACTOR_VERSION → 2026-08-28.11` (one cache invalidation for the anchor move) |
| R52.2 | The 7 flagship aliases go 0 → real lines and every TVF line is lit in the served graph | ✅ | EAST5 `f` on its JOIN line, DL `a` on each EXISTS-FROM line, RFN `p1` and `a` on both their JOIN/EXISTS lines; edges riding the alias highlight a real line. `tests/test_m_t1_tvf_alias.py` — **23 passed**, incl. multi-argument and multi-line calls, the unterminated-parens fallback, `test_ordinary_alias_anchors_are_unchanged` and `test_no_other_variable_anchor_moves` |
| R52.3 | R37.3/R37.4's ledgered L0 gap is closed | ✅ | R37.3's "TVF alias `f` anchors L0 … no-ops until M-T1" and R37.4's "1 known gap" are resolved by this row — the no-op guard itself stays (K4.4: never guess a line) |

## R53 — L2 flow-only-only UI: the Full view and the detailed views CUT FROM THE REQUIREMENT (USER RULING 2026-09-02)

> The ruling, verbatim: *"just first close full view in UI, this requirement is postponed, the source
> code is kept and not removed from git repo. We first release flow only view to user."*
> **This is a POSTPONEMENT, not a removal** — no source file, no code path, no payload field is deleted.
> Requirement statement + guarantees + rationale: `requirements_v2.md` §"Amendment (2026-09-02) — L2
> flow-only-only UI"; design decision `CLAUDE.md` #59. Frontend-only.

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R53.1 | **The L2 UI is flow-only-only**: the mode `<select>` is removed from the graph toolbar and the product's only second-level view is the line-merged flow-only closure (`flow-merged`); where the selector was, a **non-interactive static label reading "Flow only"** renders (`flow-mode-label`, no `combobox`). A user cannot reach `full-merged`, `flow` or `full` from the UI — there is no mode-change path at all, so the graph component never re-layouts on a mode switch | ✅ | 2026-09-02 — `frontend/src/components/DataFlowGraph.jsx` (`flow-mode-toggle` renders a `<span className="flow-mode-label">Flow only</span>`; the `title` states the ruling) and `DataFlowApp.jsx` (mode wiring kept, no UI entry). Absence pins in `frontend/src/components/__tests__/DataFlowGraph.test.jsx` — no `combobox` for L2 with a seed, for `viewMode={null}`, or for L1, plus the "Flow only" label assertion and the no-re-layout pin; **33/33 passed** (`npx vitest run src/components/__tests__/DataFlowGraph.test.jsx`, 2026-09-02) |
| R53.2 | **Cut guarantees (source kept)**: (a) SOURCE KEPT — every view code path stays in the repo (`flowVisibility.js`, the merged/detailed edge-id namespaces, the four `viewMode` values, the layout-persistence keys `l2:merged:{script}` / `l2:{script}`); (b) PAYLOAD UNCHANGED — the L2 response keeps the two-view contract (`flow_node_ids`/`flow_edge_ids` over the identical `full_graph`) with `relevance_filter` semantics, no backend/cache/snapshot/benchmark change; (c) REOPENING = re-expose the UI + reapply the archived full-view sibling-filter patch (and re-pin the full-view baselines it moves) | ✅ (as a contract) | The contract is what the ruling froze; rows R30.8, R32.1, R32.2 and the #331 detailed pair are AMENDED by it, not retired. The full-view sibling-filter extension was started and then postponed under the same ruling — the owning team is reverting its in-flight edits, and the patch stays ARCHIVED. SAME-DAY UPGRADE (2026-09-02, later): the user cut the Full view from the requirement entirely — the states above are final unless the requirement is re-instated |

## R54 — New edge rules from the BBZ/p_dt script investigations (USER APPROVED 2026-09-02)

Four rules the EAST5 × `BBZ` and EAST5 × `p_dt` investigations produced, plus the prune that
finishes them. Three are flow-only **admission** rules in the existing J1 pass
(`l2_builder._apply_field_involvement`, #48); 4e is an extractor/dependency-graph **anchor**
rule, so it moves `EXTRACTOR_VERSION`. The umbrella engine defect they close is the
**carrier-is-None skeleton fallback** (#426): when the hop carrier resolved to None on a
frame, the involvement filter had no sibling chip to refuse and served a foreign statement's
whole write/read plumbing as "skeleton" — the evidence the rule set now reads is the edge's
OWN carried segment (`_src_label`/`_own_seg_idx`/`_path_hops`), never its display endpoints
and never the hop the walk arrived through. Rule-by-rule examples with verbatim SQL:
`wiki/FLOW_ONLY_VIEW_RULES.md` §2h / §4e / §6d / §6e. Canonical re-pin:
`backend/tests/jaccard_canonical.py` docstring **point 27**. Requirement-level statement:
`requirements_v2.md` §"Amendment (2026-09-02) — four new L2 flow-only edge rules".

| ID | Requirement | Status | Notes |
|----|-------------|--------|-------|
| R54.1 | **2h — provenance-linked AS-alias routing (USER CONFIRMED 2026-09-02)**: a searched SOURCE field's value written to the target **under an AS-alias** keeps the alias's ⟐output legs served, so the value chain reaches the DML without a hole. Three conditions, all extraction-time facts: (a) the closure already serves the `field → alias` TRANSFORM (provenance), (b) the frame is the WRITE TARGET'S own column, (c) the statement writes no searched-field column itself (the 7-A boundary) | ✅ | enforcement = the **own-frames admission** in `l2_builder._apply_field_involvement` (audit fix F2, shipped v3.3.198 commit `e4690a7`; the 2026-09-02 tree extends the frame resolution to STATEMENT level — see R54.4): `own_frames` = every ⟐output frame a value edge writes whose source chip is the searched column (owner-checked against the searched table when `table` is passed), admitted in the Class-2 ladder (`e.source in own_frames or e.target in own_frames`) BEFORE the sibling tests. Evidence: EAST5 L50 `REPLACE(a.entd_paym_dt,"_","") As stzfrq` serves 4 edges on that line and the chain reaches the @41 DML whole (the `field → alias` TRANSFORM + the alias's write value leg + the frame membership + the searched field's own belongs-to); counter-case SUP_M L82 `… END AS reserved_field8` — the alias's value is the literal `'Rollover2'`, provenance fails, its ⟐output legs stay dropped (canonical LFS135/LFS143-145 already REMOVED by R46c). Pins: `test_field_involvement_rule.py::test_f2_own_alias_output_legs_are_served` / `…_frame_is_the_write_targets_column` / `…_boundary_written_own_column_stays_out` / `…_predicate_provenance_and_write_target` |
| R54.2 | **4e — producer-occurrence anchoring**: an edge carrying the searched field's value from a producer column anchors at the occurrence INSIDE the searched field's own producing expression (the CASE arm line), never at the collapsed group's keeper line elsewhere in the statement (EAST5 × `BBZ`: the `A.ccy_code` producer anchors **L71**, the arm-2 condition — never L47, the sibling column `bz`'s birth line; `a.charge_department` anchors **L70**, arm 1 — never L51, the `stzfdxzh` CASE's WHEN line) | ⏳ LANDING — in the working tree, ships v3.3.199/200 | enforcement = extractor **family 5** `_register_case_producer_twins` (mints the in-span occurrence twin a CASE output column's operand lacked — the L71 spelling `A.ccy_code` is a DIFFERENT alias spelling than the L47 keeper `a.ccy_code`, so `_add`'s dedup created a second var and family 3 had no collapsed occurrence to re-anchor) + `_case_arm_roles`/`_arm_role_for` (the per-occurrence CASE arm stamp) + `dependency_graph` **Phase 9b** (`_case_alias_spans` reads the `END AS <alias>` span; `_producer_occurrence_in_span` picks the twin; the move is a RE-ANCHOR, never a second edge, and the spelling-duplicate group is folded so the served set cannot depend on PYTHONHASHSEED). `EXTRACTOR_VERSION 2026-08-28.13 → .14` (new twins + moved anchors = version-matched caches must invalidate). NOT verified at doc time — no pytest was run for this record; the enforcement and its end-state pin are in the tree (`test_rule4e_producer_anchoring.py`, 14 tests, incl. `test_bbz_producer_edges_anchor_at_the_arm_lines` and the served-closure pin `test_served_bbz_closure_lights_the_arm_lines_never_the_keeper_lines`), but `wiki/FLOW_ONLY_VIEW_RULES.md` §4e still carries the ⏳ "in flight" note for the `A.ccy_code` @71 twin — the two must agree before this row flips ✅. Landing version is honest per the current tree: the whole 4e diff is UNCOMMITTED, so it ships with v3.3.199 or v3.3.200 |
| R54.3 | **6d — alias/feeder-box scope**: an alias compound and its row-source chain enter only while the searched field's producing expression reads through that alias (EAST5 × `BBZ`: `a@141` STAYS — BBZ's arms read `a.*` through it; `e@152`/`f@155` and their chain legs DROP — they feed `stzfdxzh/stzfdxhm/stzfdxhh/stzfdxxm` only) | ✅ (in the v3.3.199 pending-release tree) | enforcement = the **feeder-box set** in `_apply_field_involvement`: `feeders` = every box that owns a chip the searched field's own carried segment touches, plus each such edge's target canon; a box-level row source outside it is another column's feeder and its ALIAS/SUBSET bridge drops (`_bridge_box_carrier` admits the box skeleton only for a feeder). A box that PRODUCES the searched value at box level counts too (DL's `ods_ccb_cb_loan_acctloan@426 → LENDING_REF@101` projection). Evidence: the BBZ closure went **17 → 10 served edges** (`test_field_involvement_rule.py` header: "7 of the 17 served edges were illegal"; `test_bbz_illegal_edges_are_dropped_per_edge` + `test_bbz_legal_edges_stay_per_edge` pin both halves per edge, incl. `a@141`'s alias hop + row chain staying) |
| R54.4 | **6e — own-segment rule**: an edge is served only if its OWN carried hop segment (`‖…‖`, `_src_label`/`_path_hops` at `_own_seg_idx`) is the searched field's participation — a missing segment index is NO evidence, never hop 0 (EAST5 × `p_dt`: the job-log trunk `‖⟐output@179 → rrcdm_job_log_exec_par@179‖` drops even though its display endpoints render as the searched table's pair — `p_dt`'s only role there is the @190 filter, which stays) | ✅ (in the v3.3.199 pending-release tree) | enforcement = `_own_segment_carrier` (+ `_box_skeleton_carrier` for the table/CTE/VT-chip source class, + `_up_hop` for the Class-2 chain leg a sibling's write drives). The routed-DML write leg is the writing statement's own skeleton only when THAT statement writes the searched column into the box the leg names — resolved at STATEMENT level (the write-projection chips the closure carries), never line-vs-line: the write leg's carried target line is the write target's KEEPER occurrence (RFN @768/@1168) and the frames are compound keepers whose line is one statement's (RFN 867 vs 1429), so the old line comparison compared different statements by construction and dropped the searched field's own write legs — **restored by this carve-out** (the RFN `cust_no`→`dm_flag2` write legs the R40.12 audit recorded as written-768/written-1168; FLOW_ONLY §"charge_department" note @609). Evidence: the EAST5 × `p_dt` closure went **7 → 5 edges** (E5D4/E5D6, the job-log write trunk + its read side, removed; `p_dt`'s own @41 write trunk and the @189/@190 read/filter stay); `test_p_dt_job_log_trunk_is_dropped` / `test_p_dt_own_legs_stay` / `test_own_segment_foreign_field_drops_regardless_of_endpoints` / `test_write_leg_of_the_searched_fields_own_statement_stays` |
| R54.5 | **The orphan-BOX prune — rule 3c extended from chips to boxes**: a non-seed BOX whose every edge the involvement rule just dropped is pruned from the flow-only view, exactly like the edge-less sibling chip `_prune_orphan_sibling_chips` removes (3a/3c, #58). KEPT: every box a kept edge still touches, the searched table's own keeper, and the holder of any surviving chip | ✅ (in the v3.3.199 pending-release tree) | `_prune_orphan_boxes` (`l2_builder`, runs after the edge filter with the chip prune, before roles/assembly). Scope note: rule 3c's chip prune was deliberately scoped to FIELD chips ("table/VT compounds are skeleton"), so a box that lost its last edge stayed served — that is the hole this closes; the searched table / seed-holder box is EXEMPT. Evidence: EAST5's `rrcdm_job_log_exec_par@179` and SUP_M's `p2@199` were served as edge-less boxes and now drop, taking the whole TOP11 write frame (`⟐output` of the job-log statement) with them. Canonical point 27's NODE re-check removes **3 canonical node entries** (`iiapty↓ p2@199`, `east5↓ rrcdm@179`, the `east5↓` TOP11 ⟐output VT), superseding point 27's transient label-only re-pins — the citations name them, nothing is rewritten silently. `test_box_skeleton_of_a_non_feeder_box_drops` / `test_chain_leg_driven_by_a_sibling_still_drops` |

**Acceptance (measured on the post-fix tree; canonical = `tests/jaccard_canonical.py` point 27).**
BBZ 17 → 10 served edges (7 illegal dropped); EAST5 × `p_dt` 7 → 5 (the job-log trunk gone,
`p_dt`'s own @41/@189/@190 legs intact); RFN's own write legs restored (@768/@1168); the
jaccard gate stays **20/20 at 1.0000/1.0000 recall AND precision** — point 27 records the
three recall moves it re-derived FROM THE SQL TEXT (5 edge rows removed: `east5↓` E5D4/E5D6,
`iiapty↓` IID7/IID11, `lending_ref↑DL` LFD6) and, after the box prune, `east5↓` 3 nodes /
5 edges / 3 highlights, `iiapty↓` 6 / 7 / 4, `lending_ref↑DL` unchanged, the other 17 cases
byte-unchanged. Every removal carries an inline `REMOVED (USER RULING 2026-09-01 7-A
corollary + 3a/3c; carrier-is-None fix 2026-09-02)` marker at its old site.

## V7 — The two opposite-direction walker admissions (g1 over-inclusion, d2 over-filtering) — ✅ LANDED + SHIPPED v3.3.195

Both fixes live inside the R-GATE of `lineage._value_cone_gate`
(`backend/app/extractor/lineage.py`), both are reproducible in isolation, and both serve the user
rule "only the field involved in the data flow is shown" from the two directions it can be
violated. Traceability anchor: amends R44's admission rounds (the walker region) and R48's
field-involvement ruling; design decision `CLAUDE.md` #54.

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| V7.1 | **g1 — no cross-owner same-name REFERENCE copy is read as a producer claim** | ✅ | a same-name REFERENCE edge between two field chips on DIFFERENT owner entities is `build_dependency_graph` Phase 3's co-scope wiring (the last-writer-wins `full_col_index` pick + its bare-name fallback) — a graph-level FACT, not a value fact: the endpoints are different FIELDS. The cone crossed it twice (rule 4 admitted the foreign chip as the seed's producer, rule 6 admitted its BOX, rule 2 swept the chip back in). `_PHANTOM_COPY_GATE` gates both crossings, and the phantom CLASS is removed with the edge — a foreign same-named chip no longer HOSTS a scope, so it cannot justify its own statement's FROM leg through W6b (`src_b`/`⟐ s2` route). A cross-owner REFERENCE the consumer direction needs still crosses (`E.target_id in A`) |
| V7.2 | **d2 — a WRITE_READ reader is no longer filtered out of the closure it already reached** | ✅ | a WRITE_READ edge is the READER statement's only leg and carries no write of its own, so no clause of `_leg_justified_b` justified it and rule 6 dropped a reader box the closure fixpoint had already admitted. The reader-statement clause now mirrors the walker's own forward WRITE_READ admit (`_tf in _stmt_field_parts`): a reader that consumes the field joins, a reader that never touches it stays out |
| V7.3 | `EXTRACTOR_VERSION` is UNCHANGED (`2026-08-28.12`) | ✅ | by design, not by omission: both fixes are walker-ADMISSION only and sit downstream of every cache key — the extractor's own output (variables, dependencies, the persisted model) is bit-identical, so a bump would have invalidated every analysis, evidence and model cache in every workspace for zero effect |
| V7.4 | Blast radius: measured, not assumed | ✅ | the flagship corpus is UNCHANGED — the jaccard benchmark stays 1.0000/1.0000 on all 20 cases (none shrinks, none grows); the same equality holds over the five flagships' 1277 physical pairs and over the 108-script L2 snapshot corpus (41 expected-RED snapshots before and after — no new shift). Every before/after assertion flips the gate's OWN switches (`_PHANTOM_COPY_GATE` / `_DERIVED_CONTAINER_CHIPS`, mirror of `_VALUE_CONE_GATE`), so the "before" side is the real previous engine |
| V7.5 | Tests | ✅ | `backend/tests/test_v7_admission_fixes.py` (13), incl. `test_flagship_closures_are_unchanged` |

## H12 — Physical-model build performance (`extractor/physical_model.py`) — ✅ LANDED + SHIPPED v3.3.195

Amends the J12-10 physical-model requirement (stage 1 ships the model alongside the pipeline at
zero behavior change): "zero behavior change" now includes **byte-identical output under a
substantially cheaper build**. Design decision `CLAUDE.md` #56.

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| H12.1 | **P1** — the endpoint resolution is memoized per var id | ✅ | `_varref_memo` on `_var_ref`: it is a PURE function of the var dict (`entity_of_id`, the label map and the entity table are FROZEN before pass 3), and the dependency graph re-resolves the same variable ~10× (20,674 calls for 1,953 distinct vars on RFN). The memo is per build — it cannot leak between builds |
| H12.2 | **P7** — `PhysicalEdge` is slotted and its single_line payload is LAZY | ✅ | `__slots__` (no per-edge `__dict__`, no longer a dataclass — measured first: no `asdict`/`fields`/`replace` use, no test compares edges by value, one construction site); `flow_kind`/`reason` derive on FIRST ACCESS from `{"edge_type": …, **carried}` through the single_line strategy, computed once and cached; `highlight_line` stays EAGER (the strict walker and the lineage read it per edge). Nothing reads `flow_kind`/`reason` while building, so the eager derivation was pure waste |
| H12.3 | The model is byte-identical and the build is 31% cheaper | ✅ | **45.8 ms → 31.3 ms (−31.6%)** on RFN in situ (pass 3 was 85.7% of the build), proven byte-identical by the V6 model digest over the 10-script corpus |
| H12.4 | Minors are measured and REJECTED, with the reason recorded | ✅ | the P2 Mapping view and dropping the defensive copies: the model builds from SHARED analysis-cache dicts (the same dicts the L2 builder and the index read) and the copies are LOAD-BEARING — without them a later in-place mutation of a shared cache dict reaches the persisted model artifact |
| H12.5 | Tests | ✅ | `backend/tests/test_physical_model_perf.py` (10 — the structural invariants: the strategy is never called during the build, the payload is exactly the strategy's output, computed once, `highlight_line` eager and equal, slotted, memo per build) + `backend/tests/test_perf_byte_identical.py` (11) |

## Release gate — the ruled-red deselect policy (release.sh)

`release.sh` runs pytest at **THREE sites**: the host venv pre-flight, the `gps-sql-backend`
pre-flight, and the `gps-test` smoke stage. Policy (design decision `CLAUDE.md` #57):

1. **A ruled-red test is deselected at ALL THREE sites**, each deselect carrying the citation of
   the ruling that makes it red. A deselect added to one site only silently fails the other two —
   commits `e940782` → `05a3234` → `0ac1c81` are that history being cleaned up.
2. **A deselect is retired the moment its case goes green** — a deselect that no longer carries a
   ruling is a lie the suite tells at every release. The two lending_ref *benchmark* deselects were
   retired by `0ac1c81` when R46c turned both cases green (§R46.6).
3. **Current state: exactly 2 deselects per site** —
   `tests/test_l1_physical_model.py::test_r29_lending_ref_downstream_matches_doc` and
   `…::test_r29_iiapty_downstream_matches_doc`. They are DOC-conformance tests (the ground-truth
   doc still requires rows the canonical re-derivation removed), red-documented PENDING the user's
   job-log-continuation edge-rule ruling (`wiki/FLOW_ONLY_VIEW_RULES.md` §7-A). Suite split at the
   release gate: **1539 passed / 8 skipped / 2 ruled-red** (1549 collected).

## K4 rulings (2026-08-28) — contract amendments, recorded as design decisions

Four rulings from the K4 walkthrough. Two amend a documented contract (the code was already
right — the DOC moved, not the code), one is a new diagnostics gate, one closes the direction
API. None of them changes extraction semantics.

| ID | Ruling | Status | Trace |
|----|--------|--------|-------|
| K4.1 | **The ⟐ VT anchor is the creation line.** Top-level ⟐ output VT: the statement's OWN first token — never the `WITH` line (a CTE-bearing statement's anchor is the DML/SELECT keyword, so a click lands on the statement that produces the output, not on the clause that names an intermediate). Nested subquery/derived/EXISTS ⟐ VT: the body's first output line, falling back to the body's SELECT head | ✅ | R37.2/R37.5 amended; code unchanged (verified right) |
| K4.2 | **`parse_errors` honesty via a structural paren-balance check** — `ErrorLevel.IGNORE` recovers a partial tree from almost anything, so a statement whose parens never close parsed into a plausible graph with a clean `parse_errors: []`. `_paren_balance_errors` now runs ONE tokenizer pass over the ORIGINAL script (string/comment aware), splits at `;` TOKENS and records every statement still holding `(` open at its end | ✅ | `EXTRACTOR_VERSION 2026-08-28.7` — diagnostics ONLY (no node/line/edge moves); extraction never rejects, the detail says the recovered tree may be incomplete. CLAUDE.md decision #23 |
| K4.3 | **`direction` is accepted but NEVER honored** — every search and every L2 fetch runs downstream; an omitted value AND a legacy `"upstream"` coerce to `"downstream"` at the router boundary (`_normalize_direction`); only values outside {upstream, downstream} return 400. One direction, one mental model: "where does this field's value go" | ✅ | amends R29.4/R4.13 (R38, v3.3.180). The upstream walker machinery below the router is untouched (API-unreachable); retirement is a future work item. CLAUDE.md decision #29 |
| K4.4 | **Never guess a line: a node with no valid `line_start` (integer ≥ 1) no-ops the SQL highlight** — visible feedback instead of a silent scroll-to-top (F-B2 landed the feedback; F-B1 lands the chip `line_start` payload) | ✅ | R37.3/R37.6 — both halves shipped: the guard AND the chip `line_start` payload (R37.6 flipped ✅ 2026-09-01, `l2_builder.py:1120-1127` + `test_k4_rulings_fb1.py::TestFieldChipLineStart`) |

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
| Field chips carry `line_start`; banner text; direction default flip | ✅ FIXED (F-B1, verified in tree 2026-09-01) | R37.6 |
| Filter-operand occurrences lack their own twin edge | ✅ FIXED (F-E1, verified in tree 2026-09-01) | R44.4 |

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
| M-Po7 | Session revocation on password change (zero-expiry kept, #279) | ✅ | #319 — shipped v3.3.165 (`revoke_user_sessions` on provision force-sync). That force-sync is what every deploy runs over the R31.35 allowlist file, so a re-synced account's open sessions drop and the user logs in again |
| M-S1 (D-M1) | Search scope = physical tables/fields only — folder_index Fix A curation (R1.8) | ✅ | #308 — shipped v3.3.165 (see R1.8 ✅ row) |
| M-L1 | L1 drags saved under their own level key (not the L2 key when L2 is open) | ✅ | #309 — shipped v3.3.165 (explicit level key on `handlePositionsChange`; `resumeLayoutKey('l1'/'l2:{script}')`) |
| M-L2 | Flow-only ↔ full toggle is pure visibility — camera-stable, never re-layout | ✅ | #310 — shipped v3.3.165 (`flowVisibility.js` `.show()`/`.hide()` only; still enforced by `test_flow_line_invariants.py`) |
| H1 | Login throttling — exponential backoff, per-username + per-IP, no lockout | ✅ | #303 — shipped v3.3.165 (`auth_service.record_failed_login` backoff; residual M-A1 cardinality cap remains open) |
| #322 | R31 notification subsystem removed (no producers remain post-#285) | ✅ | #322 — shipped v3.3.165 (see R31.9 ✅ row; no `/api/notifications` route remains) |
| #320 | Low hardening backlog — 28 items, 2 covered (mark_read moot / empty-IP = M-Po4) | ✅ | #320 — shipped v3.3.165 (guards landed in folder_index, l1_builder, multi_script_service, workspace_service, audit_service, auth_service — commit `7e67f0e`) |

## Summary
| Metric | Count |
|--------|-------|
| ✅ Implemented | 235 — **2026-09-02 (§R54, the BBZ/p_dt edge rules): +4 rows → 239** — R54.1 (rule 2h, provenance-linked AS-alias routing via the own-frames admission — enforcement shipped v3.3.198 as audit fix F2, USER CONFIRMED as a rule 2026-09-02), R54.3 (rule 6d, alias/feeder-box scope), R54.4 (rule 6e, own-segment rule + the 7-A statement-level frame carve-out restoring RFN's @768/@1168 write legs) and R54.5 (the orphan-BOX prune, 3c extended to boxes) — all four are the carrier-is-None fix's admission rules, in the v3.3.199 pending-release tree. **2026-09-02: +2 rows added under §R53 (R53.1 the flow-only-only UI ruling ✅; R53.2 the postponement contract ✅-as-a-contract) — the count above is unchanged because R53 records a UI POSTPONEMENT (4 rows AMENDED in place: R30.8, R32.1, R32.2, R42.4), not new implementation. Prior 2026-09-01 (late, doc-hygiene sweep): +2 = R44.4 and R37.6, both verified LANDED in the shipped tree (⏳ → ✅). Prior 2026-09-01 (v3.3.195 SHIPPED) additions: §R46.1–R46.6 (the canonical ground-truth re-derivation R46c/R46d — 20/20 at 1.0000/1.0000 recall AND precision), §V7.1–V7.5 (the two opposite-direction walker admissions g1/d2, `EXTRACTOR_VERSION` unchanged), §H12.1–H12.5 (physical-model build 45.8 → 31.3 ms, byte-identical), plus the "Release gate — ruled-red deselect policy" section; flips ⏳ → ✅: R48.5 (the LFS41/LFS123/LFD2 rule-vs-canonical conflict RESOLVED by the re-derivation), R44.2 (benchmark re-derivation) and R44.3/R43.4 (the unified L2 snapshot regeneration ran at the release gate — 108 baselines, all green). Prior 2026-09-01 (v3.3.195 wave) additions: R49.1–R49.5 (FSC-2 model persistence — the served closure is a pure function of the SQL text), R50.1–R50.4 (H11 Phase 4d-gc MERGE-column connectivity + the G8 multi-anchor fold), R51.1–R51.4 (X1: the container-PROVENANCE bridge is deterministic, non-cyclic and KEPT), R52.1–R52.3 (M-T1 TVF alias definition lines), R31.35 flipped ⏳ → ✅ (SCR: `build_users_env` + comment stripping + the AC7 email log line + the gitignore posture, 36 allowlist tests green). Prior 2026-08-31 (v3.3.194 batch) additions: R1.9/R1.10 (fast reopen + incremental index), R2.12 (#380 participant reads), R3.7 (role-gated view "×" + child-delete routing fix), R14.5 (SSE broadcast per subscriber), R31.30–R31.33 (bounded audit trail, wedge-proof heavy gate, role-gated UI, atomic writes + meta CAS), R40.14 (self-loop caption retirement + border-scoring assignment). Prior 2026-08-31 addition: R40.12-A (Field Story rule audit amendment — 28% → 95.8% steps true of the field, frontend-only). 2026-08-29 additions: R44.1 flipped ⏳ → ✅ (occurrence coverage landed), NEW R2.11 (backend CI search, F5-extension), R5.13 (#386 CTE-scope ruling), R13.7 (simulation sample repairs, re-pin pending), R37.5 (K4 VT-anchor amendment), R40.11 (F-B2 UX hardening). 2026-08-28 additions (pending-release batch): R40.8, R41.1/R41.2, R2.9/R2.10 (F2/F5, audit #383), R5.12 (MERGE-target fold, #386), R13.6 (RFN OCR recovery #370), R40.10 (Joined/Transformed stage); prior composition: 90 R1–R16 + 17 R17–R20 + 16 R26–R28 + 8 R29 + 11 R30 + R5.10/R5.11 (#288/#289) + 33 R31 + 3 R32 + 14 R40 (R40.1–R40.14) + 2 R41 (R41.1/R41.2) |
| 📝 Partial — in progress | 0 — none (R31.2 IP audit + R1.8 search scope both closed v3.3.165) |
| ⏳ In flight | **1 row — R54.2 (rule 4e, producer-occurrence anchoring)**, ⏳ LANDING v3.3.199/200: the enforcement is in the working tree (extractor family 5 + Phase 9b, `EXTRACTOR_VERSION 2026-08-28.14`, `test_rule4e_producer_anchoring.py` 14 tests) but the whole 4e diff is UNCOMMITTED at doc time and this record ran no pytest, so the row stays open until the tree and `wiki/FLOW_ONLY_VIEW_RULES.md` §4e (which still carries the ⏳ `A.ccy_code` @71 note) agree. Prior: **0 rows** — **R44.4 (filter-operand twin edges, F-E1) and R37.6 (F-B1 chip `line_start` + banner + direction flip) flipped ⏳ → ✅ 2026-09-01 (late, doc-hygiene sweep): both verified LANDED in the shipped tree** (evidence in the rows). **Closed earlier 2026-09-01 (v3.3.195 SHIPPED): R31.35** (SCR landed), **R48.5** (resolved by the R46c canonical re-derivation), **R44.2 + R44.3 + R43.4** (the benchmark re-pin and the unified snapshot regeneration both landed at the release gate), and G7's RC-C extractor fix (R51) + G8's RC-B multi-anchor fold (R50.4). Still open with no row of its own: P2's fit-floor/header and H8's backend feature (neither recoverable from the tree), tracked in `wiki/CODE_REVIEW_2026-08-29.md` §9/§16 |
| ✅ Code-review decisions batch (2026-08-25) | 11 tasks — #303, #308–#310, #315–#320, #322 — ALL SHIPPED v3.3.165 (commit `7e67f0e`); the "Code-review decisions" table rows were flipped ⏸ → ✅ 2026-08-28 |
| ✅ Code review 2026-08-28 | 31 first-pass findings FULLY ADJUDICATED 2026-08-29 — 23 fixed, 6 false positives, 2 deferrals (verdict table: `wiki/CODE_REVIEW_2026-08-28.md` §"Resolution status (2026-08-29)") |
| ✅ Code review rounds 2026-08-30/31 | Field Story audits FSA/FSB/FSC (FSA's 28% finding fixed by G6 → 95.8%; FSB/FSC are v3.3.195-program), multi-user audits M1/M2/MSC (MSC-1 CRITICAL wedge fixed; MSC-3/MSC-6 fixed; +104 backend tests), and the R40.13 cross-check (layer PASSED, acceptance FAILED on engine closure defects RC-A/RC-B/RC-C) — record: `wiki/CODE_REVIEW_2026-08-29.md` §6–§9 |
| ✅ Code review rounds 2026-09-01 (v3.3.195 wave) | FSC-2 model persistence (R49 — the snapshot-integrity hole), H11's 7 MERGE-column connectivity defects (R50, blast radius exactly 7 corpus-wide edges, waiver reconciled), the X1 PROVENANCE relay (R51 — total-order producer pick, guard 3b, the phase KEPT), the X1/X2 review rounds (5 X2 fixes: the stats-gate OR-form, the index-run refcount, the utf-8 trail reads, the meta-404, the atomic CAS consolidation), and R40.13 cross-check round 2 (45/12/1/4, RC-A still ledgered) — record: `wiki/CODE_REVIEW_2026-08-29.md` §10–§16. **Shipped 2026-09-01 (commit `34bd521`) together with: the canonical re-derivation R46c/R46d (§R46 — 20/20 at 1.0000/1.0000, the two ruled-red `lending_ref` cases green), V7's g1/d2 admission fixes (§V7) and H12's model-build perf (§H12)** |
| K4 rulings | 4 recorded 2026-08-28 as design decisions (see the "K4 rulings" section) |
| Version | **3.3.195 RELEASED 2026-09-01** (release commit `34bd521`, deployed to prod, pushed to `origin/main`; HEAD `0ac1c81` retires the 2 lending_ref benchmark deselects) — `EXTRACTOR_VERSION 2026-08-28.12`, `GRAPH_CACHE_PREFIX graph_3_2_25`, `MODEL_CACHE_PREFIX model` |

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


- **Self-loop line style = uniform (2026-09-02, user ruling quoted in requirements_v2.md amendment)** — the merged flow-only self-loop (`filter-selfloop`) drops its special red 7px treatment and wears the uniform L2 edge style (`#7F8C8D`, width 2, mid-arrow), keeping the enlarged bezier geometry (clickable, side-assigned). Story-step emphasis falls to the generic `edge.story-active` (the special red width-9 variant is removed). Implementation `graphStyles.js`; pin `selfLoopFilterLabel.test.js`; verified by browser capture on the single flow-only view.
