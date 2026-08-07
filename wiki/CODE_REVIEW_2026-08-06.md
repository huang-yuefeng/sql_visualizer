# Code Review — v3.3.139 (D1/D2 highlight fix + B3/P1/P2 display + C-4/C-5 + join-key pairing)

> **Reviewed:** 2026-08-06 → 08-07 (round 6) | **Version:** v3.3.139, HEAD `6a19c43`
> **Scope:** commits `6692805`, `82c2c96`, `fc1cf9d`, `98f5015` (v3.3.139), `6a19c43` vs `7982efe` (`git diff 7982efe HEAD`) — highlight-pipeline fix (D1/D2), display improvements (B3/P1/P2), review-ledger items (C-4/C-5, join-key pairing), doc updates (+187 BUG_ANALYSIS, +100 this wiki, +27 CLAUDE.md).
> **Reviewer:** Codex (read-only — no source modified) via 3 parallel sub-agents: Sartre (L2+sql_line_mapper), Franklin (extractor+index), Helmholtz (docs).

## Overall verdict

The implementation claims (D1/D2, P1/P2, B3, C-4/C-5, join-key pairing, `_seen`, RELEASE.txt) are **accurate and verified** — the D1/D2/P1/P2 fix set is real, tested, and byte-exact on the highlight list. **5 items remain open/partial** (C-3 cross-run caches is the highest-risk), and the docs contain **3 overstated/unreproducible claims** to correct.

---

## ✅ Fixed & verified (green tests)

| Item | Verdict | Evidence |
|---|---|---|
| **D1** comment-line skipping | FIXED | `sql_line_mapper.py:47-49` skips `--`/`/*` lines; `test_d1_*` passes |
| **D2** highlights never 0/comment (L2 path) | FIXED | `l2_builder.py:63-66` drops `start<1`; recompute on stale caches (:54,122,151); response highlights byte-exact `[[16,16],[43,43],[52,52],[118,118],[151,151],[160,160],[204,204]]` |
| **P1** seed re-parent + scope-distance parenting | FIXED | `l2_builder.py:611-644` (seed on `l2_tbl_d5ff4bbf35`=bdm_acc_loan_info); `_scope_distance` :245 / `_pick_scope_candidate` :264 / `_resolve_scope_parent` :283 |
| **P2** target-field edges preserved | FIXED | `_promote_field_edges` skips `target_field_ids` (:825-860); seed has 4 incident FILTER edges |
| **B3** scope-distance replaces first-match (rule 1) | FIXED (partial, see open #3) | `_pick_scope_candidate` :264-281; src_tables/prefix loops stay first-match (:486-496) |
| **C-4** apply-side `n_attributed>0` gate | FIXED (round-5 #1) | `folder_index_service.py:1110` `if (n_attributed > 0 and isinstance(ul,list) and field in ul)`; M13 mismatch → cache byte-identical; `test_apply_context_mismatch_noop_does_not_touch_counters` passes |
| **C-5×C-3** star resurrection | FIXED (round-5 #2, by exclusion) | `_star_excluded = extractor_unresolved \| ambiguous_fields` (:755), per-column skip (:765); `test_star_does_not_resurrect_revoked_field` passes |
| **Join-key expr=expr pairing** | FIXED (round-5 #4, order) | `_pair_join_key_sides` deferred cross-link (`variable_extractor_v2.py:1109-1147`); both sides paired, bidirectional JOIN_KEY; `test_expr_expr_join_key_both_sides_paired` + `test_bdm_sample_join_key_expressions_all_paired` (8/8) pass |
| **C-3 per-cache guard** | FIXED (round-5 #3a) | `_revoke_s4b_cache_update` loads each cache's own `unresolved`, per-cache gate (:1164) |
| **`_seen` annotation + dangling `test_b_series_c9.py` ref** | FIXED | `variable_extractor_v2.py:450`; `test_l2_table_dedup.py:133` → `test_b_series_l2.py::test_c9_per_statement_dedup` |
| **RELEASE.txt regenerated** | FIXED | `docker_image/RELEASE.txt` VERSION=3.3.139, COMMIT=98f5015; matches repo VERSION — deploy guard no longer blocked |

### Test results
- `test_l1_l2_integration.py` 15 passed · `test_l2_table_dedup.py` 6 passed · `test_b_series_l2.py` + `test_b_series_join_keys.py` 19 passed · `test_b_series_join_keys.py` 9 passed
- `test_c_index_pipeline.py` 34 collected: **real run hangs** at `TestC5StarExpansion` (`asyncio.to_thread` in `dataflow_service.py:461` — environmental, Python 3.14 sandbox); **34 passed with to_thread stub** — CI must pin Python ≤3.12.

---

## ⚠️ Still open / partial

| # | Issue | Severity | Evidence |
|---|---|---|---|
| 1 | **C-3 cross-run stale caches NOT fixed** — prior-run scripts not re-indexed keep stale `analysis_*.json` attribution when the field IS in current `field_index` (:688-693); the cross-run glob branch (:696-698) never adds to `extractor_unresolved` → report omits the field. L1/L2 consume these caches | **High** | `folder_index_service.py:683-701` (byte-identical to 7982efe) |
| 2 | **D1/D2 is L2-path-only** — `(0,0)` still *written* at `sql_line_mapper.py:44`; unguarded consumers: `routers/variables.py:34,60`, `sql_highlight_service.py:48`, `export_config_service.py:160,203`, `sql_snippet_service.py:64,122` → stale comment anchors/`(0,0)` still surface there | Medium-High | `sql_line_mapper.py:44` vs `l2_builder.py:63-66` |
| 3 | **B3 virtual_table blind spot** — rule 1 matches `variable_type == "subquery"` only (:306-308); probe ctx `"TOP0:output"` → parentless; column branch has no first-table fallback (:455-536; expression branch does :554). Latent (0 parentless on sample) | Medium | `l2_builder.py:303-318,455-536` |
| 4 | **Duplicate display labels persist** — `p2`×7, `output`×2, `a`×5, `p1`×4 (unfiltered graph; `⟐ ` stripped :436). UI keying on `label` collides | Medium (cosmetic → latent) | `l2_builder.py:436` |
| 5 | **Alias/DML sync stmt_idx-blind** — Sync 1/2 `exists` checks `(parent,label)` only (:1183,1204); cross-statement same-name fields collapse/expand asymmetrically source vs mirror | Medium | `l2_builder.py:1158-1175,1183-1185,1204-1206` |
| 6 | **Join-key pairing name-brittle** — `by_name.setdefault(v.name, v)` first-var-wins, exact flattened-SQL match; re-render difference silently un-pairs. New data-model side effects: column vars carry expression ids in `source_variables`; expr=expr creates 2-cycles in graph JSON (inert today, unguarded) | Low-Med | `variable_extractor_v2.py:1127` |
| 7 | **C-5 exclusion case-sensitivity + over-breadth** — revoked field can re-enter under different case variant; genuinely-unresolved fields with real DDL evidence lose star-search visibility (untested behavior change) | Low | `folder_index_service.py:755,765` |
| 8 | **C-4 in-memory/persisted divergence** — on M13 mismatch, in-memory `field_index` still attributes while persisted cache keeps var unresolved; report vs cache-consumers can disagree | Low (pre-existing M13) | `folder_index_service.py:1096-1122` |

---

## 📄 Doc accuracy (Helmholtz) — implementation claims all accurate; 3 problems

1. **"Predicate line 18 covered" is false for the response** (BUG_ANALYSIS:3020) — reproduced highlights start at `[16,16]`, never hit 18; line-18 coverage is full-graph-only (`test_l1_l2_integration.py:449-453`).
2. **"All pass at HEAD: 626/5 … 40/40" overclaimed** (BUG_ANALYSIS:2862,2940) — `test_c_index_pipeline` still hangs at TestC5 under Python 3.14 in this sandbox; "40/40" matches no real count (15+24+34=73 collected).
3. **Unreproducible counts**: "12 fields preserved" (really 2 `lending_ref`-named of 12 field nodes, BUG_ANALYSIS:3021); "18 raw data_dt nodes" (4 named vars / 30 expr-referencing / 13 field nodes, :2991); "32 tests" (34 collected, wiki:51). Minor line-ref offsets (±5) and internal wording tension (7 predicate reads vs 3 output-side of "10 occurrences", :2985).

---

## 🎯 Priority advice (no source modified)

1. **Fix D1/D2 at the source** — stop writing `(0,0)` in `sql_line_mapper.py:44` and add read-time guard/recompute in the 4 unguarded consumers, not just L2.
2. **Close the C-3 cross-run gap** — revoke prior-run caches across all scripts for the ambiguous field (not only current run) and add the cross-run field to `extractor_unresolved`.
3. **Resolve B3 virtual_table blind spot** — add a VT-scope rule + column-branch first-table fallback + warn when all rules miss.
4. **Make alias/DML sync stmt_idx-aware** and disambiguate display labels (type-scoped or id-based) before any UI keys on labels.
5. **Docs**: fix the line-18 parenthetical, qualify suite-green claims with the Python version (pin ≤3.12 for CI), re-derive the 3 counts, refresh "32→34 collected".

## Verification method

- 3 sub-agents in parallel on disjoint scopes (L2+sql_line_mapper / extractor+index / docs), each verifying `git diff 7982efe HEAD` against code at HEAD `6a19c43` with live probes on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql`.
- Tests: l1_l2 15 ✅, l2_table_dedup 6 ✅, b_series_l2+join_keys 19 ✅, join_keys 9 ✅; c_index 34 ✅ (stub) / env-hang (Python 3.14 sandbox, `asyncio.to_thread` — environmental, not code).
