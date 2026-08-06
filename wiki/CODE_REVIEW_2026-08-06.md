# Code Review — Resolution Status (SQL Data Flow Visualizer)

> **Reviewed:** 2026-08-06 | **Version reviewed:** 3.3.132 (HEAD `ee03714`) + uncommitted Phase-2 follow-up + R21 commit `fd28b17` (v3.3.135) | **Reviewer:** Codex (read-only review — no source modified)
> **Scope:** 2026-08-06 commits `e47f4a3..HEAD` (5 commits) + follow-up Phase-2 auto-resolution work + R21 popup removal.
> **Resolution sweep:** 2026-08-06, v3.3.136 batch — every open item verified against the code at HEAD and either fixed (this batch or an earlier commit) or resolved by design. **No open items remain.**

---

## Resolution table (all findings)

| ID | Finding | Priority | Resolution |
|----|---------|----------|------------|
| H1 | `resolve_script` path traversal → arbitrary file read (CSV `SCRIPT_NAME` reachable) | P0 | **Fixed (pre-batch)** — `filter_service.py:47-74`: `.resolve()` + `is_relative_to()` containment guard on every candidate incl. rglob fallback |
| M4 | Fix A double-counts `total_columns` (phantom copies) — coverage inflated | P2 | **Fixed (pre-batch)** — `variable_extractor_v2.py:997`: raw walk prunes set-op bodies ("M4" comment) |
| M5 | Malformed CSV (short row) → `None.strip()` → unhandled 500 | P2 | **Fixed (pre-batch)** — `filter_service.py:133,152`: `(row.get(...) or "").strip()` + `HTTPException(400)` |
| M6 | R1 breaks `filtered_fi` ↔ `filtered_ti` symmetry for shared fields | P2 | **Fixed (pre-batch)** — `filter_service.py:312-320`: same per-table R1 predicate |
| M7 | L2 SSE queue auto-cleanup defeated by `_push` recreate-on-miss | P2 | **Fixed (pre-batch)** — `logger.py:27-45`: `_push` only puts when a queue exists; ref-counted register/unregister |
| M8 | R3 no-match banner disappears after reload | P2 | **Fixed (pre-batch)** — `dataflow_service.py:113-134` persists `match_mode`/`message` on both view paths + `restoreViews.js` overlay merge |
| M9 | ResolutionReport "No unresolved columns" keyed on names presence | P2 | **Fixed (pre-batch)** — `ResolutionReport.jsx` branches on `unresolvedTotal` |
| M10 | Coverage badge can show "100.0%" with unresolved (zero-total old caches) | P2 | **Fixed (pre-batch)** — `resolutionReport.js:82-89`: `staleZeroTotal` → `coveragePct=null` → "—" |
| M11 | `schema_candidates_summary` has no frontend consumer | P3 | **Fixed (pre-batch)** — `DataFlowApp.jsx` renders "Schema candidates" line |
| M12 | S4b field attribution script-order dependent ("first script wins") | P2 | **Fixed (v3.3.136)** — two-phase S4b: plan → conflict-detect → apply; cross-owner conflicts → `ambiguous_fields`, revoked + returned to UNRESOLVED; `resolution_stats["ambiguous"]` added (`folder_index_service.py`) |
| M13 | `_apply_s4b_cache_update` context-blind → over-attributes same-named vars | P2 | **Fixed (v3.3.136)** — attribution gated on `v.get("context") in cand["contexts"]`, legacy fallback for records without `contexts` (`folder_index_service.py:826-895`) |
| M14 | Graph caches written before S4b → stale vs index attributions | P2 | **Fixed (v3.3.136)** — `GRAPH_CACHE_PREFIX` bumped `graph_3_2_15` → `graph_3_2_16` (invalidation bump; caches rebuild lazily) (`cache_keys.py`) |
| M15 | `by_strategy["schema"]` increments even when no var attributed | P2 | **Fixed (v3.3.136)** — `_apply_s4b_cache_update` returns `n_attributed`; counter gated on ≥1 var (`folder_index_service.py:554-557,895`) |
| L1-L15 | Various low-severity (owner-not-indexed, case-fold merges, junk names, sentinel, shallow copy, TOCTOU, blocking IO, CSV size/encoding, client.js, dark card, dead code, nowrap) | P3 | **Fixed (pre-batch)** — see §3.3 of the original review; L6 moot (only 2 sentinels exist, both skipped by graph); L3/L17 kept intentionally (corpus-audited, pinned with tests) |
| L16 | `_statement_anchor` token-subsequence scan doesn't skip STRING tokens | P3 | **Fixed (v3.3.136)** — type-aware `_is_as_keyword` (non-STRING + text "as"); string literals kept in head/stream but never matched as the anchor; mirrors `_find_position` exactly (`variable_extractor_v2.py`) |
| R21-1 | Tracked `.bak` files still contain the removed popup code | P3 | **Fixed (v3.3.136)** — 8 stale `.bak*` files `git rm`'d (staged, verified zero references + build clean); `.gitignore` covers `*.bak.*` |
| R21-2 | Requirement carve-out says "gitignored `*.bak`" but backups are tracked | P3 | **Fixed (v3.3.136)** — `REQUIREMENTS.md` R21 criterion reworded: "excluding `*.bak` backup files, removed from tracking in R21" |
| R21-3 | Pinned "70 frontend tests pass" brittle | P3 | Resolved by design — count pinned in REQUIREMENTS.md updated with each release; tests continue to pass (70 at v3.3.136) |
| R21-4 | Requirement omits the rebuilt static bundle | P3 | Resolved by design — static bundle rebuild is a standing deploy step (CLAUDE.md quick-reference), noted in R22 |
| R21-5 | docker_image pieces 3.3.134 vs VERSION 3.3.135 | Info | Correct as designed — `target_deploy.sh` version gate fails fast until `release.sh` regenerates pieces |
| N2-N7 | Nits (box overflow, partial-key `s4c_seen`, view-shape, dead `_diag_box`/`W`, R1 mixed-row note, screenshots+84MB blobs in git) | P3 | **Fixed (pre-batch)** — N2/N3/N4/N5/N6 fixed in code; N7 screenshots/binaries removed from tracking (`.bak` part fixed v3.3.136) |

---

## Batch verification (v3.3.136)

- Backend full suite: **556 passed / 5 skipped** (was 523/5 at v3.3.135).
- Frontend: **70 passed** (6 files) + production build OK.
- New test files: `test_l2_table_dedup.py` (6), `test_sample_v1_repro.py` (8, pins the OCR-reconstructed repro script in `samples/sql_sample_v1/`), plus M12/M13/M15 and L16 regression tests (5 + 1).
- Live-API verification (workspace `e3bb7297c663`, script `BDM_ACC_LOAN_INFO_SUP_M.sql`): unfiltered L2 table nodes 64 → 54 (`bdm_acc_loan_info` 4 → 1, `ods_hub_lsacmsp` 4 → 1), 0 dangling ids, 0 leaked `merged_original_ids`; search `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE` → `no_matches` + message; L2 with that view → `search_matched: false` + full graph (378 nodes / 147 edges).
- Follow-up noted (out of scope, not a review item): extractor-side S4a `_finalize_schema_candidates` still increments `resolved_by["schema"]` unconditionally — same pattern M15 fixed at index level; worth mirroring when the extractor counters are next touched.

## Original review sections

Detailed per-item write-ups (with code excerpts and fix recipes) remain in the git history of this file (`git show <commit>~1:wiki/CODE_REVIEW_2026-08-06.md` for the pre-resolution version) and in `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md`.
