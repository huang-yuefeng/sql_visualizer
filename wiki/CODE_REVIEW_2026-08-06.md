# Code Review — v3.3.140/145 + working tree (strict data flow, anchors, highlight strategies)

> **Reviewed:** 2026-08-07 (round 7) | **Version:** VERSION 3.3.140; HEAD `85aac05` (labeled "docs" but **contains v3.3.145 source changes**); uncommitted working tree (I1–I5 implementation in progress)
> **Scope:** `git diff 6a19c43 HEAD` + working tree (`dependency_graph.py` +121, `variable_extractor_v2.py` +284, `lineage.py` +30, `variable.py` +2, untracked `services/highlight_strategies.py` 93 L, `tools/HIGHLIGHT_REVIEW_SAMPLE.sql` 34 L) + docs (BUG_ANALYSIS +237, wiki/SOLUTION_DESIGN +129, CLAUDE.md, wiki)
> **Reviewer:** Codex (read-only — no source modified) via 4 parallel sub-agents: Anscombe (core+old-advice), Godel (working tree), Dalton (docs), Mendel (tests; stalled, covered by Anscombe/Godel runs).
> ⚠️ **Working tree mutated during the review** (dependency_graph appeared/disappeared; snapshot ≈18:45 JST) — the change set is not yet stable; commit atomically.

## State caveats (read first)

- **HEAD `85aac05` is broken standalone**: `l2_builder.py:28`, `dataflow_service.py:26`, `routers/dataflow.py:268` import `app.services.highlight_strategies`, which exists only as an **untracked** file → fresh checkout `ModuleNotFoundError` (verified via `git archive`).
- **"docs:" commits carry undeclared code** (v3.3.145: I2 attribution removal, `highlight_strategy` param, cache `3_2_19`, `parse_errors` surface) — stop mixing code into docs commits.
- Working tree implements I1 (def-site lines), I2 (qualified-column attribution), I3 (`_pick_anchor` max-≤), I4 (`alias_of`), I5 (containment) — committed docs still say "deferred/NOT fixed".

---

## Old-advice verdict (round-6 items, at HEAD)

| # | Round-6 advice | Verdict | Evidence |
|---|---|---|---|
| 1 | C-3 cross-run stale caches (High) | **STILL-OPEN** | `folder_index_service.py:687` (`extractor_unresolved.add` only inside `if _fdata:`); cross-run branch `:694-699` never adds → report omits; prior-run scripts keep stale attribution. Byte-identical to round-6 |
| 2 | D1/D2 L2-path-only | **PARTIAL** | Root narrowed: extractor emits statement-scoped lines, `sql_line_mapper.py:57-60` lets them win; L2 guard in `highlight_strategies.py:54`. But `(0,0)` still written (`sql_line_mapper.py:54,84`); **19/253 vars on sample still `(0,0)`**; unguarded consumers unchanged (`routers/variables.py:33-34,59-60`, `sql_highlight_service.py:47-51` appends `[0,0]` unconditionally, `export_config_service.py:160,203`, `sql_snippet_service.py:64-65,122`) |
| 3 | B3 virtual_table blind spot | **PARTIAL → REGRESSION** | v3.3.140 C8 added VT to `_resolve_scope_parent` (`l2_builder.py:342-347` @1046522), but HEAD `85aac05` **deleted the whole scope-parent machinery** (I2) → column branch `:424-452` has no fallback → **9 parentless fields (filtered) / 5 (unfiltered) vs 0 at 1046522** |
| 4 | Duplicate display labels | **PARTIAL** | C3 disambiguates aliases with `@line` (`l2_builder.py:379,396`) — `p2×7 → p2@40/116/199`; non-alias intermediates still collide (`p2`×2, `accu`×2, `branch`×2, `p4`×2, `output`×2) |
| 5 | Alias/DML sync stmt_idx-blind | **FIXED (v3.3.140 C7)** | `l2_builder.py:1106-1178` — sync 1/2 exists-checks now `(parent,label,stmt_idx)`, matching dedup key `:479,:527` |
| 6 | Join-key pairing name-brittle | **STILL-OPEN (Low-Med)** | `variable_extractor_v2.py:1127` `by_name.setdefault(v.name,v)` first-var-wins; **4 same-rel JOIN 2-cycles** on sample; unguarded |
| 7 | C-5 exclusion case-sensitivity | **STILL-OPEN (Low)** | `folder_index_service.py:755,765` — exact-match `_c in _star_excluded`, no case normalization |
| 8 | C-4 in-memory/persisted divergence | **STILL-OPEN (Low, pre-existing)** | `folder_index_service.py:1110` apply-side gate; M13 mismatch → in-memory attributes, cache keeps unresolved |

**Tally: 1 FIXED, 3 PARTIAL, 4 STILL-OPEN.** Nothing touched `folder_index_service` (C-3/C-4/C-5).

---

## New findings (v3.3.140 + working tree)

| # | Severity | Finding | Evidence |
|---|---|---|---|
| N1 | **High** | HEAD cannot boot without untracked `highlight_strategies.py`; imports at `l2_builder.py:28`, `dataflow_service.py:26`, `routers/dataflow.py:268` | `git archive HEAD` → `ModuleNotFoundError` |
| N2 | **High (transient)** | dependency_graph I3/I4/I5 edits broke v3.3.140-pinned tests (`test_dependency_count` 644<660, `test_same_table_4_contexts_single_node` lost SUBSET) — later reverted; current tree still fails 2 tests (below) | `test_sample_v1_repro.py:67`, `test_l2_table_dedup.py:107` |
| N3 | **Medium** | **Parentless-field regression at HEAD** — I2 deleted parent fallbacks; 5–9 parentless on sample (0 at 1046522) | `l2_builder.py:424-452` |
| N4 | **Medium** | **Write-side DML asymmetry** in strict walker — `lineage.py:626-627` `DML: admit=fwd`: query on output table's field never reaches producers (`bdm_acc_loan_info_sup.data_dt` closure = 6 nodes, source-side reaches target) | `lineage.py:523,626-627` |
| N5 | Low-Med | `(0,0)` still written for 19/253 vars (7.5%: ⟐ VTs + rendered CONCAT expressions); L2 path safe, other consumers not | `sql_line_mapper.py:54,84` |
| N6 | Low-Med | Strict-walker identity edge cases — unqualified-owner rule needs exactly one table-like var in context (`lineage.py:471-505`); ambiguous → no seed → `search_matched=False`; `_field_part` last-segment skips expression-labeled computed vars; `_find_labeled` returns `ids[0]` no tie-break | `lineage.py` |
| N7 | Medium | **I5 containment dead end-to-end** — `dependency_graph` tags 1 edge, but `adapter._dep_to_dict` (`:157-165`) and `graph_service.build_graph_data` (`:233-244`) drop `containment` → `lineage._is_containment` never fires; rollover→⟐subq edge still renders | `variable.py:111,127`, `adapter.py` |
| N8 | Medium | **A3 parse_errors dead** — recorded in `extract_variables_from_sql` (`variable_extractor_v2.py:274,428-447`) but `run_full_analysis` returns no `parse_errors` key → `dataflow_service.py:384,390`, `l2_builder.py:156` always `[]`; new frontend UI can never show anything | `variable_extractor_v2.py`, `DataFlowApp.jsx` |
| N9 | Medium | **I3 removes first-match fallback → pinned test regression not updated** (`test_same_table_4_contexts_single_node` asserts SUBSET edge); `_pick_anchor` requires `1<=x.line_start<=v.line_start` → line-0 vars get no bridge (conflates "synthetic" with "lookup failed") | `dependency_graph.py:421-451,484-540` |
| N10 | Low-Med | **Cache-bump doc lies**: `cache_keys.py:40-52` claims `3_2_19` pairs with "B3/C5 picker deletion" — `l2_builder.py` still contains `_pick_scope_candidate`/`_scope_distance`/`_resolve_scope_parent` (`:283-362`, now mostly dead code) | `cache_keys.py`, `l2_builder.py:283-362` |
| N11 | Low | `highlight_strategies._single_line_ranges` `int(line_start)` raises `ValueError` on malformed cache → 500, no try/except; `label_only`/unknown-name fallback/registry **untested**; frontend never passes `highlight_strategy` (design wanted a config key) | `highlight_strategies.py:41` |
| N12 | Info | `tools/HIGHLIGHT_REVIEW_SAMPLE.sql` matches header lines but **not referenced by any test** (v3.3.144 open item: → pytest fixture) | file |

---

## Doc↔code discrepancies (Dalton)

1. **Cache prefix wrong in all 3 docs** — CLAUDE.md:31/145, SOLUTION_DESIGN:908, BUG_ANALYSIS:3053 say `graph_3_2_18`; code (HEAD + WT) = `graph_3_2_19`.
2. **SOLUTION_DESIGN §4 `FIELD_LIKE` list wrong** — docs list `{…, computed, window, variable}`; `VariableType` has no `computed`/`variable`; code uses `{…, case, transform, window}` (`lineage.py:403`). Code comments already flag the doc error.
3. **v3.3.144 "no new fields needed / already exists" false at HEAD** — `alias_of`/`containment` are **new WT fields**; and the adapter **drops both** → I5 inert (doc's I5 expectation 13→12/18→17 not met; WT actual 11/5 with containment edge still present).
4. **S1/S2/S3 + I1–I4 "deferred/NOT fixed" stale vs WT** — I1/I2/I3/I4 implemented and probe-verified (anchors `data_dt@160→bdm_acc_loan_info_sup@160`, `data_dt@213→rrcdm@211`, `ods_hub_lsacmsp@33→bdm@29`).
5. **v3.3.144 "B machinery DELETED" overstated** — `_find_position_scoped` remains for columns/reads; only def-site (tables/aliases/CTE/subquery/DML/CREATE) converted.
6. **Internal doc contradiction** — v3.3.143 I3 proposes line-containment anchors; v3.3.144 rejects it (no sqlglot positions) and uses max-≤; :143 never marked superseded.
7. **CLAUDE.md File Map stale** — references deleted `_pick_scope_candidate`; line counts off (l2_builder 1317→1297, dataflow_service 485→527, variable_extractor 2120→2178, cache_keys 32→43, lineage 683→669).
8. **Phantom-dedup "before" numbers don't reproduce** — doc 344→253 vars / 1102→660 deps; measured 354/1126 at `6a19c43` (sqlglot 30.8.0 vs doc's 30.12.0). After-numbers verified exactly.
9. **"635/5" and "40/40" suite claims unverified/overclaimed** (same class as round-6 flag).

---

## Test results

| Tree | Result |
|---|---|
| **Pristine v3.3.140 (`1046522`)** | **29 passed** — v3.3.140 itself green |
| **HEAD `85aac05` + untracked** | **27 passed / 2 failed**: `test_same_table_4_contexts_single_node` (no SUBSET edge), `test_dependency_count` 644<660 |
| **Working tree** | 2 failed / 37 passed — `test_b3_zero_parentless_fields` (pre-existing, parentless `lending_ref, data_dt, internal_key,…`), `test_same_table_4_contexts_single_node` (I3 regression, not updated) |
| `test_c_index_pipeline` | environmental hang (asyncio.to_thread, Python 3.14 sandbox) — unchanged; CI must pin ≤3.12 |
| highlight-related tests | pass individually (`test_d2_highlights_never_zero_or_comment_lines`, `test_data_dt_highlights_cover_predicate_line`, `test_target_highlight_lands_on_keeper`); `-k highlight` full run hangs (workspace fixture) |

---

## Priority advice (no source modified)

1. **Commit `highlight_strategies.py` with its wiring** (or move import behind fallback) — HEAD is un-buildable standalone; stop shipping code in "docs:" commits.
2. **Fix C-3 cross-run gap** (highest open item): revoke prior-run caches across all scripts + add cross-run fields to `extractor_unresolved`.
3. **Restore a deliberate parent fallback** for the I2-deleted machinery — 5–9 parentless fields is a regression vs 1046522 (drop unattributable or attach with warning).
4. **Wire I5 + A3 end-to-end**: serialize `alias_of`/`containment` in `adapter._var_to_dict/_dep_to_dict` and `parse_errors` through `run_full_analysis`, or remove the half-implementations.
5. **Update the stale pinned test** for I3 (`test_same_table_4_contexts_single_node`) — SUBSET bridge removal is intentional per v3.3.143, so re-scope the expectation.
6. **Docs**: single-source cache prefix (→ `cache_keys.GRAPH_CACHE_PREFIX`, currently `3_2_19`); fix SOLUTION_DESIGN §4 FIELD_LIKE; mark v3.3.143 superseded; refresh CLAUDE.md file map; flip I1–I4 statuses once committed.

## Verification method

- 4 sub-agents in parallel (core+old-advice / working-tree / docs / tests), each with live probes on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql` + `tools/HIGHLIGHT_REVIEW_SAMPLE.sql`; `git archive` fresh-checkout check for the untracked-module break; byte-exact highlight re-probe `[[18,18],[43,43],[158,158],[160,160]]`.
- No source files modified.
