# Code Review — v3.3.147 edge-driven highlights (round 10, open issues only)

> **Reviewed:** 2026-08-10 | **Version:** VERSION `3.3.146` (WT = v3.3.147 in progress) | **HEAD:** `e20174b` (docs) + **large uncommitted working tree** (v3.3.147 implementation: extractor W2/W6, edge-driven highlight payload, frontend EdgeReasonPanel)
> **Scope:** working tree vs HEAD — `dependency_graph.py` +155, `lineage.py` +14, `variable_extractor_v2.py` +351, `l2_builder.py` +414, `highlight_strategies.py` +207, `dataflow_service.py` +36, `routers/dataflow.py` +13, `sql_range_finder.py` **deleted (−708)**, tests +~1000, frontend 8 files + 4 new test files.
> **Reviewer:** Codex (read-only — no source modified) via 4 sub-agents: Wegener (extractor), Copernicus (services), Avicenna (tests), Fermat (frontend) + main-thread scoping.
> ⚠️ Working tree mutated during review (extractor edits 18:29–19:21 JST after tests written 17:52) — pins are stale; commit atomically after re-pinning.

## Resolved since round 9

- **E5** — Phase 4d READ is now `REF/READ` (not SUBSET/READ); bare columns get READ edges; sample SUBSET count **129 → 1** (only intentional B1 bridge remains).
- **Line resolution (W2/W6 landed)** — `data_dt@225` (WHERE clause) now resolves; VT creation-line stamping (`⟐ output@160/211`, `⟐ subq@26`, `⟐ subq1@22`); line-0 vars **19 → 7**; `_find_position`/`_find_position_scoped` cleanly deleted.
- **Frontend v3.3.147 spec implemented** — no field highlight (`SqlPanel.jsx:28,300-314`), edge-driven single-line highlight (`highlight_line`/`flow_kind`/`reason` on edges), kind-only edge labels (`graphStyles.js:677-693`), EdgeReasonPanel mounted below SQL (`DataFlowApp.jsx:664`), `onBgTap` guard fixed (`useCytoscapeGraph.js:111-114`). **81/81 frontend tests pass.**

---

## Open issues

### High

1. **Benchmark regression gate RED — 38/40** (`test_ground_truth_benchmark.py`). Tests build the **raw** graph and assert `highlight_line` there, but the W5 payload is attached only at L2 build (`_attach_flow_payload`) → W5 "has landed" but the tests never run `_build_l2_graph`. On top: node bijection failures (closure now **85 nodes/294 edges** bdm, **70/224** sup vs pinned 16/24, 8/12 — VT nodes now stamped at creation lines, not `@0`), `PAIR18_KNOWN_GAP=True` while the W2 fix landed (pair 18 present: `data_dt@225→bdm_acc_loan_info_sup@223`), 13/32 `test_edge_lines` rows fail (11 MISSING + 2 multi-edge pairs needing `rel_hint`). | Route fixtures through `_build_l2_graph`; flip `PAIR18_KNOWN_GAP=False`; re-pin node/edge constants to the current WT.
2. **Closure explosion — strict table.field flow semantics broken** (Wegener probe; baseline vs WT): `sup.data_dt` **8→70**, `bdm.data_dt` **16→85**, `charge_department` **5→66**, `lending_ref` **5→66** — all four now contain `rrcdm_job_log_exec_par@211` and cross-field columns (`p1.data_dt@158`, `p2.data_dt@202`, INSERT column swarm). Cause: Phase-8 re-typing turns never-walked SUBSET bridges into walkable REF/JOIN/FILTER/DML. Closures are no longer field-specific. | Keep Phase-8 bridges as SUBSET (never walked) for non-field pairs, or explicitly accept component-level closures and re-pin.
3. **`sql_range_finder.py` deletion is NOT clean** — `tests/test_l1_l2_integration.py:36` and `tests/test_filter_andor.py:1` still `from app.services.sql_range_finder import find_sql_range` → **ModuleNotFoundError at collection; CI broken**. | Delete/port the 2 test modules (their range cases are obsolete).

### Medium

4. **D2 — WRITE_READ still field-blind (partial fix)**. Backward VALUE admit is gated on `_field_part(nb)==target_field` (`lineage.py:664-681`), but plain forward `admit = fwd` for DML remains unconditional → `rrcdm@211` still appears in `charge_department`/`lending_ref` closures (66 nodes each, same as round 9). | Gate forward DML admit on stmt2 referencing target_field.
5. **E1 — 1c-direct cross-statement CTE gate still missing** (`dependency_graph.py:260-272`): statement-level branch checks only `tbl_var.context == stmt`, never `src.context`; spurious `x@2(TOP0 cte) -TABLE_FLOW/INSERT-> out_tbl@4(TOP1)` reproduced. | Add `if (src.context or "TOP") != stmt: continue` (mirror :257).
6. **E2 — 1c-cross no time/order guard** (`dependency_graph.py:202-229`): reversed write-after-read phantom WRITE_READ reproduced. | Skip when writer line_start > reader line_start.
7. **D1 — 100-round cap silent partial closure unchanged** (`lineage.py:646,650-681`): no in-round `stack.append(nb)`, no cap-exit warning; 150-hop REF chain → 102/152. | Re-push admitted nodes in-round; log on cap exit.
8. **N8 — parse_errors still dead end-to-end** (`adapter.py:128-145`, `dataflow_service.py:382`): `run_full_analysis` return dict still omits `parse_errors` → always `[]`. | Add `"parse_errors": [dict(e) for e in extract_result.parse_errors]`.
9. **API contract change not propagated to tests** — `highlights` response field + `highlight_strategy` query param removed; `test_full_http_journey.py:185`, `test_search.py:120`, `test_l1_l2_integration.py:487` still assert them (KeyError / collection error). | Update/delete stale assertions.
10. **B1 bridge endpoint corrupted** (`l2_builder.py:1000-1007`): step-2 DML bypass redirect rewrites `e["target"]` of SUBSET/BRIDGE `sup@223→rrcdm@211` to `⟐ output` while carried `_tgt_label/_tgt_line` still say `rrcdm@211` → graph endpoint contradicts reason string. | Exclude SUBSET/SCHEMA from step 2 (or re-carry after re-pointing).
11. **N11 — `int()` guard still missing (relocated)** (`highlight_strategies.py:91-92`, `l2_builder.py:659-660`): `int(e.get("_src_line") or 0)` raises ValueError on malformed cache string; no try/except anywhere; untested. | Defensive `try: int(x) except: 0` + unit test.
12. **2/149 L2 edges emit `highlight_line=0`** (`highlight_strategies.py:91-92`): the CONCAT join-key expression vars (`CONCAT(RPAD(p4.iiapty,3,''),p4.iiblno)@L0`) leak line 0 into the payload contract ("line 0 is a defect" per §8.3). | Anchor the 7 CONCAT join-key expressions (line_map fix) or suppress line-0 read edges.

### Low

13. **D3 — rule-(b) qualifier-agnostic** (`lineage.py:683-699`): VT branch matches any visited field var with `_field_part==target_field` under the VT's context, ignoring owner. Latent (0–1 fires on sample). | Also constrain by resolved owner/qualifier == target_table.
14. **F9 — `_simplify_dml_edges` picks first `⟐ output` VT** (`l2_builder.py:943-958,1011-1027`): stmt-2's write points from TOP0 node while reason says `@L211`. Cosmetic; anchor stays correct. | Pick intermediate per statement context.
15. **F10 — dead carriers** (`highlight_strategies.py:42`, `l2_builder.py:663-671`): `_VT_TYPES` unused; 6 `_src_vt/_tgt_vt/...` carried but never consumed. | Drop or consume.
16. **Frontend label vs line color mismatch** (`graphStyles.js:677-693`): label `color: data(color)` (type color) vs `CATEGORY_EDGE_STYLES` line-color wins later → DML/AGGREGATE/JOIN/TRANSFORM labels differ from their rendered lines; comment at :673-675 misleading. | Source label color from the same value painting the line.
17. **Self-loop pair 11 never reaches the frontend** (`l2_builder.py:707-708` `if src_new == tgt_new: continue`): deliberate SELF_JOIN `sup@160→sup@160` dropped → "every edge highlights" contract unmet for pair 11; no loop style exists either. | Don't drop deliberate SELF_JOIN loops (skip only merge-created ones); add loop style.
18. **Layout clip risk** (`app.css:693-706` + `DataFlowApp.jsx:664`): `.panel-inline-l2` non-flex with `overflow:hidden`; fixed 400px graph + draggable SQL + fixed 92px reason panel can exceed viewport height → reason panel clipped; renders even when sqlText empty. | Flex column + `min-height:0`; render panel only when sqlText set.
19. **Stale selection on "Show All"** (`DataFlowApp.jsx:342-347`): `handleToggleFilter` sets `l2Graph(l2FullGraph)` without clearing `selectedEdge` → stale SQL highlight/reason for an edge absent from view. | `setSelectedEdge(null)` in Show-All branch.
20. **Leftover debug probes (8, untracked)** — `backend/_probe213.py`, `backend/app/_probe213.py` (byte-identical, hardcoded `/app`), `_check33.py`, `_dump_resp.py`, `_probe211.py`, `_probe_fix4.py`, `_probe_pins.py`, `_probe_walk.py`, `_e2e_probe.py`. | Delete before commit.

### Docs / process

21. **Benchmark spec still hardcoded, doc drift** (`test_ground_truth_benchmark.py:111-157` vs `GROUND_TRUTH…md §8.5`): test doesn't read the .md; doc says 33 entries, test default 32 (gated pair 18); doc pins `⟐…@0`, code emits creation-line keys; doc claims 16/24, code gives 85/294. | Single-source from the .md or assert test constants == doc §8.5 (round-9 L2 advice, still open).
22. **Count pins dropped, growth unasserted** (`test_ground_truth_benchmark.py:436-454`): old 253 vars/737 deps pins removed; actual **253 vars / 774 deps (+37)** only printed. | Re-pin or document the 737→774 delta as deliberate.
23. **`variable_extractor_v2.py:798` whole-stream keyword fallback** uses `runs[-1:]` with first-occurrence-in-stream → multi-INSERT scripts can anchor VT on the wrong statement's keyword line. | Prefer scoped-only matching for keyword runs.
24. **W2 `loose_first` adjacency relaxation** (`variable_extractor_v2.py:1725-1741,810-869`): first `where` token + next `col_name` anywhere in the statement can couple different clauses. Usually line-correct. | Accept (documented) or scope to the clause's braces.
25. **Frontend a11y + legend nits** — EdgeReasonPanel: no `role="status"`/`aria-live` on dynamic reason; SUBQUERY listed only under `chain` (doc §8.7 row 13: `field flow / chain`). | Add aria-live; annotate per-edge kind.

---

## Test results (working tree)

| File | Result |
|---|---|
| `test_ground_truth_benchmark.py` | **38 failed / 2 passed** — pins stale (see #1/#2/#21/#22); ~18 failures NOT the documented W5-expected ones |
| `test_verification_samples.py` (new) | **13 failed** — all `hl is not None` (W5 payload not on raw graph); matches documented expected state; all 13 edges exist |
| `test_highlight_strategies.py` | **16 passed** (payload unit tests sound) |
| `test_edge_validity.py` / `test_b_series_l2.py` | 30 / 10 passed |
| Extractor-level suites (variable_extractor, dependency_graph, i1_definition_lines, edge_types, graph_integrity, node_types) | **184 passed** |
| `test_l1_l2_integration.py` / `test_filter_andor.py` | **Collection ERROR** (sql_range_finder import, #3) |
| Frontend (vitest) | **81/81 passed** |
| Async files (`test_search`, `test_single_script_l1`, `test_filter_config`, `test_full_http_journey`, `test_c_index_pipeline`) | sandbox hang (asyncio.to_thread, py3.14) — environmental |

Probe (sample `BDM_ACC_LOAN_INFO_SUP_M.sql`): VARS=253, DEPS=774, GRAPH_EDGES=774, PARSE_ERRORS=[]. Closures (WT): sup.data_dt=70, charge_department=66, lending_ref=66, bdm.data_dt=85.

## Priority advice (no source modified)

1. **Unblock CI first**: fix the 2 `sql_range_finder` imports (#3), then re-pin the benchmark (#1/#22) and flip `PAIR18_KNOWN_GAP` (#1).
2. **Decide closure semantics (#2)**: accept component-level closures + re-pin, or keep Phase-8 bridges non-walked — this determines whether D2 (#4) and the whole "strict field flow" claim can be met.
3. **Finish the round-9 carryovers**: N8 parse_errors (#8), N11 int guard (#11), D1 in-round stack (#7), E1/E2 gates (#5/#6).
4. **B1 endpoint consistency (#10)** and line-0 CONCAT edges (#12) before the payload contract is relied on.
5. **Frontend**: label/line color alignment (#16), self-loop rendering decision (#17), layout (#18), stale selection (#19).
6. **Housekeeping**: delete the 8 debug probes (#20), drop dead carriers (#15), fix doc spec drift (#21), run `release.sh` on a clean tree when v3.3.147 ships.

## Verification method

- 4 sub-agents in parallel (extractor / services / tests / frontend), each with live pipeline probes on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql` (/tmp venv, sqlglot 30.8.0, fastapi from backend/vendor), synthetic-SQL probes (CTE cross-statement, reversed time, 150-hop chains), baseline-vs-WT closure diffs, and frontend vitest runs (81/81).
- No source files modified.
