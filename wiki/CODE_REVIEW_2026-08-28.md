# Code Review — 2026-08-28 (uncommitted delta vs HEAD v3.3.190)

**Reviewer:** code-review agent + 4 parallel sub-agents (backend-extractor / backend-services / frontend / tests-sample-harness).
**Scope:** uncommitted working-tree changes vs `HEAD = ca653a4` (`VERSION=3.3.190`). Committed v3.3.171–190 releases are covered separately by `CODE_REVIEW_PENDING_2026-08-27.md`.
**Method:** static review only; no source modified; no full suite run.

---

## Verdict

The in-progress batch is broadly sound but has **3 High** items — two real frontend regressions
(dropped `recenter` propagation; a `minZoom` change that breaks an existing test guard) and one
sample SQL corruption (empty-literal join key in `BDM_ACC_LOAN_INFO_RFN.sql`). The backend
extractor/services slices show mostly Medium logic gaps (MERGE-target fold typing, bare-INSERT set-op
merge, S4b/star-expansion script-attribution holes). Version stamping is now consistent at 3.3.190
(earlier drift resolved).

---

## HIGH

### H1 — Fit's `recenter:false` is silently dropped (frontend regression)
- `frontend/src/utils/flowVisibility.js:45-50` — `fitAllElements` destructures only
  `flowOnly/flowNodeIds/flowEdgeIds/mergedView` and omits `recenter`, so the `recenter:false` passed by
  the Fit handler (`useCytoscapeGraph.js:481`) never reaches `applyFlowVisibility` → Fit still re-centers
  on the seed and can keep nodes off-screen.
- **Fix:** add `recenter` to the destructuring and forward it:
  `applyFlowVisibility(cy, { flowOnly, flowNodeIds, flowEdgeIds, mergedView, recenter })`.

### H2 — `minZoom` 0.28 → 0.08 breaks an unchanged test guard
- `frontend/src/hooks/useCytoscapeGraph.js:262` changed `minZoom` 0.28→0.08, but
  `frontend/src/utils/__tests__/selfLoopFilterLabel.test.js:187` still regex-asserts `/minZoom:\s*0\.28\b/`
  → suite fails.
- **Fix:** update the test guard to `0.08` (or revert `minZoom` if 0.28 is still the intended contract).

### H3 — RFN sample join key collapsed to an empty-literal comparison
- `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql:492` — `AND REPLACE(p8.X5TERM,' ','') = ''` makes the
  rate-lookup join key compare against the empty string (only blank `X5TERM` rows match), silently replacing
  the prior OCR-uncertain reconstruction.
- **Fix:** restore a real RHS (verify from source; the earlier `REPLACE(P1.X5TERM,' ','')` also referenced a
  column `P1` doesn't expose) and keep the `[OCR-UNCERTAIN]` marker until confirmed.

---

## MEDIUM

### Backend extractor (lineage.py / variable_extractor_v2.py / sql_model.py)
- **M1** — `variable_extractor_v2.py:1386` — write-side twin type filter omits `VariableType.LITERAL`, so
  constant projections (`1 AS flag`, `'x' AS col`) never get a `{target}.{col}` twin (only `NULL` does, as
  EXPRESSION) → those written columns lack a physical field entity. Add `LITERAL` to the allowed set.
- **M2** — `variable_extractor_v2.py:1438` — derived-read scope check is too narrow/inverted (`sctx == vctx or
  startswith(vctx+'/')/'/'`); misses a derived alias referenced from a deeper nested scope (e.g. `p2.col` inside
  `TOP0/subq/x` while the subquery is `TOP0/subq/p2`). Compare `_scope_top(sctx) == _scope_top(vctx)`.
- **M3** — `variable_extractor_v2.py:565` — bare-INSERT merge only handles a following `exp.Select`; a
  `SELECT … UNION ALL SELECT …` source parses as `exp.Union` and isn't merged → write legs stay severed.
  Also accept `exp.Union/Intersect/Except`.
- **M4** — `lineage.py:1360` — derived-product holder selection picks the first owner-entity occurrence whose
  name equals `st2[0]` with no context constraint; can select a read of the searched table from a different
  statement (cross-statement over-inclusion). Prefer the holder whose context matches/ancestors `o2["context"]`.

### Backend services / routers (l2_builder / folder_index_service / topology_checker / workspace)
- **M5** — `folder_index_service.py:859-861` — S4b attribution adds the field to `table_index[owner]` but never
  adds `_srec` to `field_index[_f]["scripts"]` → schema-resolved fields still report "field not queried" in
  `create_search`. Add `field_index[_f]["scripts"].add(_srec)` (and `table_index[owner]["scripts"].add(_srec)`).
- **M6** — `l2_builder.py:58-60` — `_PARTITION_DDL_STMT` allows arbitrary tokens between `DROP`/`ADD` and
  `PARTITION`, so it over-matches column DDL (`ALTER TABLE t DROP COLUMN partition`, `ADD COLUMN x COMMENT
  'PARTITION'`). Require adjacency: `(?:ADD|DROP)\s+(?:IF\s+NOT\s+EXISTS\s+)?PARTITION`.
- **M7** — `l2_builder.py:585,703` — adding `merge_target` to the physical fold without adjusting `tbl_type`
  makes the keeper order-dependent: a MERGE-target occurrence processed first becomes `intermediate_table`,
  later `table` occurrences fold into it → misclassification + broken `source_table` parent fallbacks.
  Classify non-output physical merge targets as `source_table`.

### Frontend
- **M8** — `FilterPanel.jsx:105-106` (rendered 295-298 / 326-329) — `tableMissing`/`fieldMissing` become true on
  the first keystroke (while the index is still empty/loading), showing a red "no such table/field" even when
  suggestions are visible. Gate on empty dropdown results and `!loading`, or track an explicit failed Enter.

### Tests / sample / harness
- **M9** — `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql:351` — `CASE WHEN P1.IGJQA IS NOT NULL OR
  SUBSTR(P1.IGJQA,4,1)<>'9'` uses `OR`; the 4th-char test is dead whenever `IGJQA` is non-null. Almost certainly
  `AND` (matches the `IS NULL OR …='9'` fallback at lines 604/629).
- **M10** — `backend/tests/test_l2_case_merge.py:335` — `"\n".join(reversed(…split("\n")))` reverses individual
  lines, producing invalid SQL (`WHEN MATCHED…;` precedes `MERGE INTO`), so "read first, MERGE second" is never
  actually exercised. Swap the two whole statements instead of reversing lines.
- **M11** — `backend/tests/test_folder_index_cte.py:128` — `if "r" in ti:` makes the alias-entry assertion
  vacuous; if the alias entry is absent the test body no-ops and passes. Assert `"r" in ti` (or the intended
  shape) before checking its `scripts`.
- **M12** — `backend/tests/test_jaccard_benchmark.py:1058` — docstring promises "no direction can print above
  1.0", but the only assertion is `round(val,4) >= floor`; a >1.0 recall/precision still passes. Add an
  upper-bound assertion (`<= 1.0`/`<= 1.0001`).
- **M13** — `backend/tests/test_flow_line_invariants.py:79-100` — R43 DDL guard asserts only `not ddl_covered`
  and never asserts an `ALTER TABLE … p_dt` line exists; if the fixture loses its partition-DDL lines the guard
  silently stops testing anything. Count DDL lines and assert non-empty first.

---

## LOW

### Backend extractor
- **L1** — `lineage.py:834` — R0 makes table-name seed match case-insensitive but still compares
  `fname != target_field` case-sensitively → case-variant field search yields no downstream seeds. Use `.lower()`.
- **L2** — `lineage.py:1576` — anchorless-edge exclusion keys physical edges by split `edge_type`, but graph edges
  carry compound `relationship` (`"REF,DML"`) → compound edges never excluded. Split `relationship` before keying.
- **L3** — `variable_extractor_v2.py:1296` — synthetic flow twins created via `_add` as `COLUMN` inflate
  `_resolution_stats["total_columns"]`/coverage_pct. Register twins without touching counters.
- **L4** — `variable_extractor_v2.py:1399` — `len(alias) > 64` guard silently drops valid long write columns, and
  unaliased non-NULL expressions auto-name to junk (`t.NULL`, `t.ROW_NUMBER…`). Derive alias from target column
  list; guard only empty/invalid names.

### Backend services / routers
- **L5** — `l2_builder.py:107-114` — `_drop_partition_ddl_frames` removes only the `⟐ output` VT + incident edges,
  leaving the ALTERed table as an isolated node (contrary to the "statements shouldn't appear" ruling). Also drop/
  isolate statement-frame occurrences or filter zero-edge table nodes.
- **L6** — `l2_builder.py:65-74` — `_statement_text_from_line` anchors on the VT line + requires text to start with
  `ALTER`; single-line multi-statements (`SELECT …; ALTER TABLE …`) and >200-line statements are missed. Use the
  extractor's statement anchors/span.
- **L7** — `folder_index_service.py:929-931` — star expansion adds fields to `table_index[_t]` but not
  `table_index[_t]["scripts"]` → fields-without-scripts for alias/CTE/derived star sources. Add `.add(_rel)`.
- **L8** — `folder_index_service.py:644,672,705` — unconditional script attribution turns script-scoped
  CTE/alias/derived names into workspace-wide searchable table entries (conflicts with R20). Skip CTE names/`⟐`
  markers or restrict to physical tables.
- **L9** — `workspace.py:230` — `scan_workspace` is `async def` but calls blocking `scan_folder` on the event loop
  (parses every SQL file). Make it sync or run via `run_in_executor`.

### Frontend
- **L10** — `fieldStory.js:7,49,56,308` — header + `buildFieldStory` JSDoc still document the 5-stage order
  `born→written→read→filtered→consumed` and omit the new `joined` stage. Update docs.
- **L11** — `graphStyles.js:19` (+ `useCytoscapeGraph.js:257-261`) — comment claims labels "hide" below readable
  zoom, but `min-zoomed-font-size: 6` keeps them visible at 6px. Correct the comment or set size 0/`text-opacity`.

### Tests / sample / harness
- **L12** — `tools/ocr/harness.py:378-398` — `_parse_statements` docstring claims it survives `;` inside
  literals/comments, but the whole-script-parse-failure fallback `sql_text.split(";")` (line 387) reintroduces
  that corruption. Use sqlglot tokenizer/statement iterator for the fallback.
- **L13** — `tools/ocr/harness.py:364-373` — `_SQL_KEYWORDS` denylist is incomplete (missing MERGE/USING/ALTER/
  DROP/COLUMN/KEY/PRIMARY/FOREIGN/DEFAULT…). Derive keywords from sqlglot tokenizer or a complete set.
- **L14** — `backend/tests/test_tvf_row_source.py:124-127` — disconnected-case assertion hard-codes the exact
  production message string; a cosmetic message change fails a behavioral test. Assert a stable prefix/substring.
- **L15** — `frontend/src/utils/__tests__/hoverEnlarge.test.js:103` — minZoom "test" regexes the hook source text
  for `minZoom: 0.08` rather than asserting the runtime option. Inspect the actual option / mount-driven assertion.

---

## Cross-cutting (verified this round)

- **Version stamping now consistent at 3.3.190** — `frontend/index.html:19`, `backend/app/static/index.html:19`,
  `CLAUDE.md:14`, `REQUIREMENTS_TRACEABILITY.md:1`, `docker_image/RELEASE.txt` all read 3.3.190 (the prior
  M-D1 drift is resolved).

## Not reviewed

- Full test-suite execution (Python 3.14 sandbox); static analysis only.
- The 41 rebaselined snapshot JSONs (45k insertions) were not line-audited — spot-checked for consistency only.

---

## Addendum — 2nd pass: newly-modified files since the first pass

Scope: files that entered the uncommitted-modified set **after** the first pass above
(delta-of-the-delta). 4 parallel sub-agents.

### HIGH

- **H4** — `backend/app/extractor/dependency_graph.py:556` — the new
  `_add_edge(t, v, "SCHEMA", "TABLE_COLUMN")` is counted by Phase 8's `ec` (only `SUBSET` is excluded), so the
  twin now has `ec=2` (Phase 3 already adds an incoming `REF/REFERENCE`) and Phase 8's `if ec >= 2: continue`
  skips it → the `twin → owner REF/READ` bridge the block's own comment says Phase 8 emits is dropped.
  **Fix:** emit `_add_edge(v, t, "REF", "READ")` alongside the SCHEMA edge, or exclude SCHEMA from the `ec` count,
  or run this block after Phase 8.

- **H5** — `backend/tests/test_orphan_resolution_index.py:132-140` — TC1 now asserts bare `SELECT id` resolves to
  `t1`, but `id` in `SELECT id FROM a JOIN b` is a source column (`a.id`/`b.id`), not `t1.id` — it codifies a false
  attribution and erases the never-guess guard. **Fix:** keep `field_index["id"]["tables"] == []` and assert the
  INSERT-target `t1.id` twin separately as the target-list occurrence.

### MEDIUM

- **M14** — `backend/app/services/highlight_strategies.py:137` — WINDOW override anchors on `_tgt_line` (the window
  var's `line_start`), which for multi-line `OVER (...)` is the `AS <alias>`/closing-paren line, not the partition-key
  line the comment claims. **Fix:** carry an explicit OVER-clause line from extraction.
- **M15** — `backend/tests/jaccard_canonical.py:486-488` vs `:1357` — docstring says "26 new rows LFS80–LFS105 /
  77→103 edges" but LFS106 is also added → actually 27 rows / 104 edges; the "served: 103 edges" cross-check is stale.
  **Fix:** recount to LFS80–LFS106 / 77→104.
- **M16** — `backend/tests/test_l1_physical_model.py:361` — upstream test adds PL as a second writer but `tables`
  still lacks PL's source `ods_cupd_ploan_acctm_new5` (the docstring cites it as chain start @220). **Fix:** add it,
  or document the exclusion.
- **M17** — `backend/tests/jaccard_canonical.py:1275-1285` — LFS80–85 "physical-side" rows duplicate existing
  LFS16–23 (same src@41/type/anchor) with only the dst weakened to `⟐subq@0`; label-only `@0` doesn't encode the
  alias-vs-physical distinction claimed. **Fix:** pin instance-distinguishing evidence, or drop the duplicates.
- **M18** — `backend/tests/test_graph_integrity.py:64-89` — twin detection (dotted column whose prefix ==
  `source_tables[0]` with non-empty `source_columns`) can't distinguish occurrence twins from genuine schema members
  → can mask real `column_connectivity` regressions. **Fix:** detect twins via an explicit extractor flag/type.
- **M19** — `backend/tests/test_orphan_resolution_index.py` (module docstring + TC3/TC4) — the only assertion that an
  ambiguous field has empty `field_index[...]["tables"]` was removed with TC1; TC3/TC4 no longer pin the never-guess
  guard. **Fix:** re-assert `field_index["id"]["tables"] == []` in TC3/TC4.
- **M20** — `backend/tests/test_l1_l2_integration.py:127` — `assert {e["source"] for e in joins}, joins` only checks
  the set is non-empty (already implied by `len(joins)==2`), so it never verifies the docstring's "distinct sources"
  claim. **Fix:** `assert len({e["source"] for e in joins}) == 2`.
- **M21** — `frontend/src/utils/__tests__/selfLoopFilterLabel.test.js:187` — the 0.28→0.08 update is correct and
  matches `useCytoscapeGraph.js:262`, but the test still regexes raw source text, not runtime behavior. **Fix:** assert
  the returned config/`cy.minZoom() == 0.08`.
- **M22** — `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md:34` — §2.2 "Downstream L1 (reading)" Scripts list
  adds `BDM_ACC_LOAN_INFO_Digitallending`/`_PL` (the seed's upstream **writers**, not downstream readers).
  **Fix:** keep §2.2 to readers (`_SUP_M`), or rename/clarify the section.
- **M23** — `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md:27` — §2.1 Tables omits PL's chain-start
  `ODS_CUPD_PLOAN_ACCTM_NEW5` (alias `a`, @220) while listing DL's equivalent `ods_ccb_cb_loan_acctloan`.
  **Fix:** add it.
- **M24** — `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_LENDING_REF.md:11` — "Writers (two)" omits `BDM_ACC_LOAN_INFO_RFN.sql`
  (writes the seed @866/@1167). **Fix:** include RFN, or document the 3-script subset and why RFN is excluded.

### LOW

- **L16** — `backend/tests/test_orphan_resolution_index.py:120` — test name `test_tc1_scope_absent_schema_owner_stays_unresolved`
  contradicts its new assertions (0 orphans, id→t1). Rename.
- **L17** — `backend/tests/test_orphan_resolution_index.py:175-176` — `test_tc3b` docstring still says tc1_ws's `id`
  "leaves unresolved". Update.
- **L18** — `backend/tests/test_physical_model_equivalence.py:238-242` — docstring enumerates 13 new write-side twins
  but the test only asserts the aggregate count (37). Assert the 13 names.
- **L19** — `backend/tests/test_graph_integrity.py:118-123` — waiver matches exact string prefix `[column] {name}: `;
  a wording change silently disables it, and the single-REF witness may still trip `isolated_nodes`. Waive on structured identity.
- **L20** — `backend/tests/jaccard_canonical.py:1311-1333` — LFS92–103 copy-REF rows use label-only src (`poacs@0`),
  matching either `poacs@41` or `@117`. Use line-scoped src endpoints.
- **L21** — `backend/tests/test_l1_l2_integration.py:132` — hard-codes `highlight_line == {5}` + direct indexing
  (KeyError risk). Derive from SQL text or use `.get()`.
- **L22** — `backend/tests/test_full_http_journey.py:213,222` — comment says "5 hops" but the listed path is 4 hops and
  the assertion also requires `stg_orders`. Fix the comment.
- **L23** — `backend/tests/test_s4_instrumentation.py:120` + `test_s4b_resolution.py:197` — test names contradict the
  R44 assertions they now make. Rename.

---

## Totals (both passes)

High: H1–H5 (5) · Medium: M1–M24 (24) · Low: L1–L23 (23). First pass: 3H/13M/15L; second pass: 2H/11M/8L.

---

## Resolution status (2026-08-29)

Adjudicated the same day, against the working tree (every verdict below was checked in code, not
taken on trust). The original findings text above is UNCHANGED — this section only records
verdicts. Scope: the **31 first-pass findings** (H1–H3, M1–M13, L1–L15). The second-pass
addendum (H4/H5, M14–M24, L16–L23) is triaged at the bottom.

**Tally over the 31 first-pass findings: 23 FIXED · 6 FALSE POSITIVE · 2 DEFERRED (one of them
— L4 part 2 — inside an otherwise-fixed row) · 1 folded into an addendum follow-up (L15 → M21).**
The Fixed table below has 24 rows: the 23 first-pass fixes PLUS **M14** from the second-pass
addendum, which was fixed by the same batch (listed here because it is the OVER-line WINDOW
anchor half of R44).

### Fixed (23)

| ID | Fix | Verified where |
|----|-----|----------------|
| H1 | `recenter` forwarded through `fitAllElements` → `applyFlowVisibility`; `recenter:false` (user Fit) skips `centerOnSeed` | `flowVisibility.js:45-50,319-321` |
| M1 | Write-side twins admit `VariableType.LITERAL` — constant projections materialize a `{target}.{col}` twin | `variable_extractor_v2.py` (`_register_flow_occurrence_twins` family 1); changelog 2026-08-28.5 item 5 |
| M2 | Derived-read scope check REWRITTEN as a binding-scope comparison (holder context == read context or an ancestor of it) — no `startswith` guessing | `lineage.py` holder resolution (`_hctx == o2_ctx or o2_ctx.startswith(_hctx + "/")`) |
| M3 | Bare-INSERT merge also merges a following `exp.Union`/`Intersect`/`Except` | changelog 2026-08-28.5 item 6 (`_walk_insert` merged_select path) |
| M4 | Derived-product holder selection is context-constrained: read occurrences win, DML-target occurrences are only a fallback of last resort, and a same-named holder outside the read's scope can never win | `lineage.py:~1345-1380` |
| M5 | S4b attribution records `field_index[_f]["scripts"].add(_srec)` (and the owner's `table_index[...]["scripts"]`) | `folder_index_service.py:866,868` |
| M6 | `_PARTITION_DDL_STMT` requires adjacency: `(?:ADD\|DROP\|MSCK)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?PARTITION\b` | `l2_builder.py:58-61` |
| M7 | Non-output MERGE targets classify as `source_table` — keeper type no longer order-dependent | `l2_builder.py` fold (`_TABLE_LIKE` includes `merge_target`) + `test_t3_merge_target_folds_into_physical_keeper` |
| M10 | The "read first, MERGE second" case swaps the two WHOLE statements (never line-reversed) | `test_l2_case_merge.py` `test_t3_read_first_order_folds_too` |
| M11 | The alias-entry assertion is no longer vacuous: `assert "r" in ti` before checking its `scripts` (fixed by an earlier team; verdict confirmed real) | `test_folder_index_cte.py:128-133` |
| M12 | Upper-bound assertion added: `assert round(val, 4) <= 1.0001` alongside the floor | `test_jaccard_benchmark.py:1066` |
| M13 | INV-1 counts the DDL lines and asserts non-empty BEFORE the exclusion assert | `test_flow_line_invariants.py:88-92` |
| M14 | WINDOW edges anchor on the OVER application line (`highlight_strategies._anchor_line`), carried from extraction | changelog 2026-08-28.4 item 2 |
| L1 | Downstream seed match compares `fname.lower() != target_field.lower()` | `lineage.py:~834` |
| L4 (part 1) | The `len(alias) > 64` silent drop is gone; the guard is now semantic: a projection with NO alias (`_auto_named_outputs`) is skipped as junk-name, not length-capped | `variable_extractor_v2.py` family 1 |
| L5 | The ALTERed table's own occurrence, left isolated by the frame drop, is dropped too (still edge-connected in another statement → kept) | `l2_builder.py:115-129` |
| L7 | Star expansion records `table_index[_t]["scripts"].add(_rel)` | `folder_index_service.py:943` |
| L8 | Script attribution no longer turns script-scoped CTE names into workspace-wide tables: the `source_tables` candidate skip `⟐` markers and `cte_names` | `folder_index_service.py:632-636` (F2's R2.9 invariant is unaffected — it applies to entries that legitimately receive fields) |
| L9 | `scan_workspace` is plain `def` (threadpool, not the event loop) | `workspace.py:229-235` |
| L10 | `fieldStory.js` header + `buildFieldStory` docs now read `born → written → read → joined → filtered → consumed` (6 stages) | `fieldStory.js:7,35,51,101` |
| L11 | The comment now states the truth: `min-zoomed-font-size` pins a 6px floor, it never hides | `graphStyles.js:17-21` |
| L12 | `_parse_statements` no longer falls back to a bare `split(";")`; the tokenizer-derived statement path is the only path | `tools/ocr/harness.py` |
| L13 | `_SQL_KEYWORDS` derives from sqlglot's `Tokenizer.KEYWORDS` with a pinned tail that includes the previously-missing DDL words (MERGE/USING/ALTER/DROP/COLUMN/KEY/PRIMARY/FOREIGN/DEFAULT) | `tools/ocr/harness.py:_sql_keywords` |
| L14 | Disconnected-case assertion checks the stable parts (offending column name + the connection phrase), not the exact production string | `test_tvf_row_source.py:121-131` |

### False positives (6)

| ID | Why it is not a defect | Evidence |
|----|------------------------|----------|
| H2 | The `minZoom` test guard was updated in tandem with the 0.28 → 0.08 change (both files land in the same batch) — the suite was never left asserting the old floor | `selfLoopFilterLabel.test.js:186-187` and `hoverEnlarge.test.js:102-103` both assert `/minZoom:\s*0\.08\b/`, matching `useCytoscapeGraph.js:262`. (The "stop regexing source text" half is a separate, still-open style point — M21/L15.) |
| H3 | RFN L492 `AND REPLACE(p8.X5TERM,' ','') = ''` is what the source screenshot shows — the #370 re-derivation resolved all 21 `OCR-UNCERTAIN` markers with pixel evidence and the line stands | `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql:492` (0 markers remain in the file); R13.6 |
| M8 | The "no such table/field" message is the F5 contract, not a false alarm: it renders only for a typed name that resolves to no index key in ANY casing, and Search stays disabled while `loading` | `FilterPanel.jsx:107-108,312-315,344-347,352` |
| M9 | RFN L351's `OR` is the authored text; the sibling fallback blocks use the same `IS NULL OR SUBSTR(...)` shape the reviewer cited as the evidence FOR `AND` | `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql:351` vs `:604`; R13.6 |
| L2 | Anchorless-edge exclusion is keyed on the MODEL's `PhysicalEdge` (one `edge_type` each), not on the graph edge's compound `relationship` string — there is nothing to split | `lineage.py:~1576-1590` (`for _E in physical_model.edges: _k = (_E.source_id, _E.target_id, _E.edge_type)`) |
| L3 | Twins are real `COLUMN` variables minted through the same `_add` path as every other column, so the R20 coverage denominator is SUPPOSED to include them; excluding them would understate the column population. No counter bypass exists or is wanted | `variable_extractor_v2.py` `_add` (`if var_type == VariableType.COLUMN: total_columns += 1`) |

### Adjudication record — the three K3 judgment-call repairs (NOTE #16, 2026-08-29)

- RFN `:492` (empty-literal RHS `= ''` — H3 above), RFN `:800-801` (the `field = 'IS_SIENCE_TECH' AND value = '1'` filter demoted to a trailing comment) and RFN `:903` (the invented `AND '$(load_date)' <> '2024-08-31'` guard) are REPAIRS, not transcription: each is a judgment call the #370 pixel pass authenticated (`screenshots/case2-1..13.png`; 0 `OCR-UNCERTAIN` markers left), none machine-verifiable from the pixels alone. Red-team flag: **truth matters if wrong** — they are baked into the unified L2 rebaseline CONSCIOUSLY, and any future re-derivation that disagrees must re-adjudicate against those pages, not silently re-edit. Mirrored in `wiki/CODE_REVIEW_PENDING_2026-08-27.md` §5 → "#386 rulings" item 6.

### Deferred (2, evidence-based)

| ID | What is deferred | Reason |
|----|------------------|--------|
| L6 | Using the extractor's statement anchors/spans for partition-DDL detection | The conservative line-anchored detector (`_statement_text_from_line`, 200-line bounded scan + `ALTER TABLE … (ADD\|DROP\|MSCK) … PARTITION`) never over-drops a real dataflow frame; wiring extraction spans into a display-layer projection is a redesign with no demonstrated false-negative in the samples. Revisit if a sample shows a missed frame |
| L4 (part 2) | Deriving the write-slot name from the target column list | Not positionally recoverable: projection outputs do not register 1:1 in source order (fin_query4_merge_upsert TOP1 — an 11-item SELECT with an 11-name column list registers 10 outputs), so an index map would silently MIS-name. Replaced by the part-1 guard: skip the twin rather than mint a bogus physical field |

### Folded (1)

- **L15** — the minZoom constant-pin test still asserts source text rather than the runtime option. Folded into the addendum's **M21** (same subject, same file); the R41 fix did update both tests to the 0.08 floor.

### Second-pass addendum (H4/H5, M14–M24, L16–L23) — triage

Verified in code: **H4 fixed** (Phase 4d-gb emits the twin's SCHEMA connectivity edge while
Phase 8 keeps the REF/READ bridge — `dependency_graph.py:542-562`); **M14 fixed** (see above);
**M17 fixed** (LFS85 re-pinned 2026-08-29 at its own occurrence line — the label-only `⟐subq@0`
"physical-side twin" pin the finding described is gone, with the reasoning in a row comment);
**M18 fixed** (twin detection is now a structured signature with an explicit write-twin
carve-out — `_r44_derived_read_twin_names`, `test_graph_integrity.py`); **L22 fixed** (the
comment now says 5 hops with the R44 rationale); **L23 fixed** (the two test names now match
their R44 assertions — `test_insert_list_evidence_no_column_vars`,
`test_scope_absent_evidence_never_attributed`);
**H5/M16/M19/L16/L17/M22/M23/M24 addressed as documented rulings** — the orphan-resolution tests
now assert the R44 authored-evidence rule with its reasoning in the docstring, TC3 still pins the
never-guess guard (`unresolved: 2` for the ambiguous `id`,
`test_orphan_resolution_index.py:120-180`), and `GROUND_TRUTH_..._LENDING_REF.md` §1/§2 records
the PL write leg + the retired field-vs-table exclusion with evidence.

Still open (doc/test pinning suggestions, no behavioural risk, left in this file unadjudicated):
M15 (docstring still says "26 new rows LFS80-LFS105 / 77→103"; the file carries 27 rows
LFS80–LFS106), M20, M21, L18, L19, L20, L21. None of them changes engine output.

### Second-pass leftovers closed (2026-08-29, cleanup team CL)

All seven items adjudicated against the working tree the same day; each line below is the closure
record (files touched: `backend/tests/jaccard_canonical.py` (comments only),
`backend/tests/test_l1_l2_integration.py`, `backend/tests/test_graph_integrity.py`,
`backend/tests/test_physical_model_equivalence.py`, `frontend/src/hooks/useCytoscapeGraph.js`,
`frontend/src/utils/__tests__/selfLoopFilterLabel.test.js`, `frontend/src/utils/__tests__/hoverEnlarge.test.js`).

- **M15 FIXED** — point 17's "26 rows / 37→38 nodes / 77→103 edges / served 49-103" figures are stamped as THAT round's measurement with a count re-base recording the later additions (LFS106 #387; LFS107-110 + the pogmab@46/poctcd@120 nodes, F-D 2026-08-29) and the CURRENT canonical tally, re-derived from the module: **40 `CANONICAL_NODES_DIR` entries / 107 `CANONICAL_EDGES` rows** for lending_ref↓SUP_M (stamped in all three stale spots: docstring point 17, the LFS80-110 block comment, the node-list comment). `jaccard_canonical.py` is comment-only — benchmark unchanged at 18 passed / 2 failed (the two known F-E2 owner-defects).
- **M20 FIXED** — the vacuous `assert {e["source"] for e in joins}, joins` became `assert len({e["source"] for e in joins}) == 2`, pinning the docstring's "distinct field instance, NOT a duplicate" claim (`test_l1_l2_integration.py`, 14 passed).
- **M21 FIXED** — `minZoom` is asserted at RUNTIME: the hook's core cytoscape options are hoisted into an exported `CY_CORE_OPTIONS` (frozen; spread into the `cytoscape(...)` call — values/behaviour unchanged) and `selfLoopFilterLabel.test.js` pushes it through a REAL headless cytoscape instance (`cy.minZoom() === 0.08`, `cy.maxZoom() === 5`) plus an identity-based wiring check that the hook still spreads it; `hoverEnlarge.test.js` (the folded **L15**) asserts the same imported object. Source regexes for the minZoom VALUE are gone. Frontend suite 26 files / 268 tests green.
- **L18 FIXED** — the 13 write-side twins are pinned BY NAME (`r44_write_twins ⊆ set(sup.fields)`, each name commented with its projection line), not only via the aggregate 37; `test_flagship_field_count_sup` passes.
- **L19 FIXED** — the waiver parses the checker's issue IDENTITY (`[<type>] <name>:` header + isolated_nodes' edge count) instead of matching the literal prose prefix: a wording change can no longer silently disable it (an unparseable issue naming a waived twin now fails with an explicit "update `_ISSUE_HEADER`" message), and the waiver extends to `isolated_nodes` for ≥1-edge read twins (the single-REF witness) while a 0-edge twin stays a hard error. `test_graph_integrity.py` 24 passed; probe-verified live (14 column_connectivity issues waived today, 0 isolated_nodes twins).
- **L20 PARTIALLY RESOLVED + adjudicated NOT-A-BUG for the rest** — the rows the finding flagged as ambiguous ARE line-scoped now (LFS92/94/96/98 src @117; LFS100-103 re-pinned to the operand's own line by F-D 2026-08-29). The four remaining label-only srcs (LFS93/95/97/99 `poacs@0` …) are deliberate and now documented in-file: those operands have NO second in-scope occurrence, so the copy's source instance carries BOTH lines' evidence and a line-scoped src would invent evidence the SQL does not select. No row pin changed.
- **L21 FIXED** — the expected JOIN line is derived from the sample SQL (`ON so.customer_id = sc.customer_id`) instead of the hard-coded `{5}`, and the highlight set reads `e.get("highlight_line")` (a missing line fails as a mismatch, not a KeyError). Covered by `test_l1_l2_integration.py`'s 14 passes.

Test evidence: `tests/test_jaccard_benchmark.py` 18 passed / 2 failed (pre-existing, F-E2-owned);
`tests/test_graph_integrity.py` 24 passed; `tests/test_l1_l2_integration.py` 14 passed;
`tests/test_physical_model_equivalence.py` 11 passed / 1 pre-existing engine-side failure NOT from
this batch (`test_every_display_edge_has_model_witness`, 529 vs 530 edges — the F-E2 occurrence-twin
work in flight); frontend `vitest run` 26 files / 268 tests passed. No git commits.
