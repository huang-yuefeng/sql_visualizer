# Code Review — Open Issues (SQL Data Flow Visualizer)

> **Reviewed:** 2026-08-06 (round 2) | **Version reviewed:** v3.3.136, HEAD `c82161d` (R22)
> **Scope (new since last review):** `cb58c28` (Phase-2 + review fixes), `67e8b89` (A1 schema-file classification + 5-team dispatch), `d4922d0`, `2babb12`, `8a80417` (deploy guard), `c82161d` (L2 dedup + search semantics).
> **Reviewer:** Codex (read-only — no source modified) via 3 sub-agents (backend commits / frontend+tests / backend batch).
> **Content:** new open issues only.

---

## Open issues

| ID | Severity | Area | Issue | Suggested fix |
|----|----------|------|-------|---------------|
| P1-1 | **High** | A1 classifier `folder_index_service.py:44–67` | CTAS-only `.sql` files (`CREATE TABLE … AS SELECT`, i.e. `kind==TABLE` **with** an `expression`) are classified as `"schema"` → the CTAS body's output fields vanish from search/L1–L2 | Treat `kind==TABLE` **with** `expression` present as `"script"`; add a CTAS regression test |
| P2-2 | Medium | Graph cache vs S4b `cache_keys.py:24`, `l2_builder.py:99–106` | The `3_2_16` bump invalidates stale graph caches, but rebuild runs `run_full_analysis` fresh and **never loads the S4b-mutated analysis cache** → rebuilt graphs still lack S4b cross-script attributions; L1 (analysis caches) vs L2 (graph caches) stay divergent | `index_scripts` must rewrite/delete graph caches **after** the S4b pass, or L2 must load the analysis cache and re-derive `source_tables` |
| P2-3 | Medium | S4b revocation `folder_index_service.py:523–531` (new) | Ambiguity revocation is **index-only**: `_fdata["tables"].clear()` + `fields.discard()` never touch analysis/graph caches → a revoked field still carries `source_tables=[old_owner]`/`resolved_by` in caches; L1/L2 still show the old attribution | On revocation, clear `source_tables` on matching vars in owning scripts' analysis caches and invalidate their graph caches — or keep the stronger S1–S3/S4a attribution and only refuse the S4b claim |
| P2-4 | Medium | Persisted resolution counters `folder_index_service.py:554, 874–877` | In-memory `by_strategy["schema"]` is gated on `n_attributed>0`, but the **persisted** cache `rs["resolved_by"]["schema"] += 1` and the `unresolved` drop still run even when `n_attributed == 0` → in-memory and cache counters disagree | Gate the persisted counter/drop on `n_attributed` too (mirror the extractor-side S4a counter) |
| P2-5 | Medium | `dataflow_service.py:52–70` `create_search` | Table-only union fallback removed (deliberate per BE2), but scripts referencing a table via `SELECT *` / indirect expression uses may now disappear from L1 unless the extractor materializes the field | Verify `SELECT *`/expression sources are indexed; add a regression for table-only references |
| P2-6 | Medium | Frontend test coverage | No `DataFlowApp` component test for the reload no-match banner or the new L2 not-in-flow banner (only pure-function `restoreViews.test.js`); R22 headline acceptance (repro script L2: 1 node for `bdm_acc_loan_info`, 54 table nodes, `search_matched:false`) is **untested end-to-end** — `test_sample_v1_repro.py` stops at extractor/index invariants | Add L2-level regression using `samples/sql_sample_v1/`; add component tests for banner rendering |
| P2-7 | Medium | `target_deploy.sh` guard edges | Missing `RELEASE.txt` degrades to a warning (should fail fast); remote-check can advise `reset --hard origin/main` downgrade when fetch fails or local is newer | Make missing `RELEASE.txt` fail fast; guard the downgrade advice |
| P3-8 | Low | `logger.py:32–40` | Queue recreate-on-miss fix now **drops log messages** for runs starting before the SSE stream connects (looks like a hang) | Bounded tombstone/deque buffer instead of dropping |
| P3-9 | Low | `l2_builder.py:337–345, 376–384` | Field dedup key `(parent_table_id, label)` over-merges distinct computed expressions with identical labels (`sum(x) ↻` in two statements of one script collapse into one node) | Key expressions by `(parent, label, context/statement)` |
| P3-10 | Low | `dataflow_service.py:355–370` | `not_in_flow` calls `_build_l2_graph` twice (full analysis twice if cache missing); fallback highlights the entire full graph | Single unfiltered build + flag; scope highlights to non-empty ranges |
| P3-11 | Low | `DataFlowApp.jsx:626, 411–416` | Reload banner can flash during a new search (not gated on `!loading`); cached "Show All" branch bypasses `applyL2Result` → `l2NotInFlow` not refreshed | Gate banner on `!loading`; route "Show All" through `applyL2Result` |
| P3-12 | Low | `routers/dataflow.py:107–126, 141–142` | `_load_base_index` + exact-case dict lookups: case-variant search (`"orders"` vs `"Orders"`) yields misleading "not queried by any indexed script" suggestion | Normalize case or add a case-insensitive hint |
| P3-13 | Low | Perf | A1 re-parses the whole tree 2–3× per index; `_statement_anchor` is quadratic (`variable_extractor_v2.py:481–544`) | Reuse one parse; index anchors by position |
| ENV-1 | Info | Test env | `test_filter_config.py` deadlocks here (anyio threadpool + `asyncio.run`, pre-existing) → +67 R17 tests can't run in this sandbox; backend full suite needs fastapi | Add `pytest-timeout` guard or HTTP-level test client; re-run on CI |
| ENV-2 | Info | `dataflow_service.py` / `l2_builder.py` behavior | `create_search` change and dedup collapse are deliberate but user-visible; keep the noted regression tests | — |

---

## Verification this round

- Tests run here: backend targeted **96 pass** (l2_table_dedup 6, s4b_resolution 24, sample_v1_repro 8, s4_instrumentation 35, orphan_resolution 13, l1_l2_integration 10) + fastapi-free subset; frontend **70 pass** (6 files) + production build OK.
- `.bak` cleanup complete: zero `scriptInfo`/`script-info-popup`/`sip-header` references; nothing tracked.
