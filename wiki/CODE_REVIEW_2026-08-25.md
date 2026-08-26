# Code Review — 2026-08-25 (v3.3.166)

**Reviewer:** code-review agent (consolidated from 2 rounds × 5 parallel sub-agents)
**Scope:** `v3.3.166` (commits `6c9e729` feat + `5cf860f` release), which shipped the ISSUE-4 case-insensitive table-identity rework, L2 line-merged views, and the benchmark harness.
**Method:** static review only — no source modified, no full suite run.

---

## Verdict

v3.3.166 **fixed 5 of my prior extractor/test findings** (H-E1 correlated subquery, M-E2 `_scope_top`, M-E4 `_ident_votes`, L-E7 `_norm`, L-E8/L-E9 tests) and **re-baselined the L2 snapshots correctly** (no data loss; `EAST5_STZFXXB` filtered view actually gains correct edges).

Still open after this round: **1 new extractor regression** (M-E3 partial → qualifier fold), a **flawed benchmark node-precision metric**, the **frontend flow-visibility High**, **2 security Highs**, and a **large doc-staleness cluster** — the docs still say "queued / awaiting GO / no source change" in the *same commit* that ships the code.

---

## HIGH (open)

### H-F1 — Edge-only flow closure: toggle ON but full graph rendered (frontend, still open)
- `frontend/src/utils/flowVisibility.js:22-27` vs `:61-64`. `resolveFlowOnly` returns `true` for an edge-only closure, but `applyFlowVisibility` short-circuits on empty `flowNodeIds` and calls `cy.elements().show()`. Contradicts the documented "edge-only closure must enable View 1" contract. `v3.3.166` only touched `DataFlowApp.jsx` (cosmetic copy) + `app.css` (a11y/numeric) — `flowVisibility.js` untouched.
- **Fix:** only short-circuit on `!flowOnly`; when nodes are empty, drive visibility from `flowEdgeIds` endpoints.

### H-S1 — Login backoff `time.sleep()` blocks the async event loop → unauthenticated self-DoS (still open)
- `backend/app/routers/auth.py:65` (`time.sleep(record_failed_login(...))`) inside `async def login`, plus sync 600k-iteration PBKDF2. `/api/auth/login` is public; a handful of failed logins stalls the whole service.
- **Fix:** `await asyncio.sleep(...)`; run credential check via `asyncio.to_thread`.

### H-S2 — Hardcoded weak default admin credential (still open)
- `backend/app/config.py:42` `{"admin@hsbc.com": "123456"}`, force-synced each startup. Guessable on first attempt despite #303 rate limiting.
- **Fix:** provision admin from env secret with a strong/generated password, or force first-login change.

### H-D1 — Documentation cluster: shipped code still recorded as "queued / no source change" (still open, expanded)
All of the following ship in v3.3.165/v3.3.166 but the docs claim otherwise:
1. `requirements_v2.md:70-71` — code-review amendment still "implementation queued, awaiting GO" (shipped v3.3.165).
2. `wiki/REQUIREMENTS_TRACEABILITY.md:303-321` — 11 decision tasks marked `⏸` (shipped v3.3.165).
3. `wiki/REQUIREMENTS_TRACEABILITY.md:299-301` — **new** R32.1/R32.2/R32.3 marked `⏸` though shipped v3.3.166 (`l2_builder.py:1850 build_line_merged_edges`, `dataflow_service.py` emits `flow_only_merged`/`full_merged`); the `⏸` summary count (`:328`, "11 tasks") is now stale — there are **14 ⏸ rows**.
4. `wiki/REQUIREMENTS_TRACEABILITY.md:22,271` — R1.8 (#308) and R31.2 (M-Po4) still "partial" though both gaps are closed in v3.3.165.
5. `wiki/REQUIREMENTS_TRACEABILITY.md:1,330` — title/Version still **3.3.164** (HEAD 3.3.166).
6. `wiki/SOLUTION_DESIGN.md:1807-1876` — R31 section still "awaiting go / no code changed", still describes the removed notification inbox / self-register / 30-min TTL / `/api/notifications`.
7. `wiki/SOLUTION_DESIGN.md:1884-1886` — **new** R32 section "Design; no source change yet" appended in the same commit that ships the source.
8. `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:5178/5235/5242` — ISSUE-4/5/6 statuses still "OPEN / no-source-changes / queued" though implemented v3.3.166.
9. `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:5190-5220` — **new** ISSUE-5 "Fix direction" proposes a *fully case-folding* `_norm`, but the shipped `test_jaccard_benchmark.py:397-401` folds only the map-key lookup and keeps the fallback case-preserving (deliberately, to catch canonical-spelling regressions). The doc describes the not-shipped design.
- **Fix:** one coordinated docs sweep — flip `⏸`→`✅`, "queued/awaiting GO"→"shipped", bump versions to 3.3.166, delete removed-feature prose (notifications/visits), and reconcile counts (partials, `⏸`).

---

## MEDIUM (open)

### M-E3b — `_canonicalize_table_names` step 3 folds alias/CTE/derived qualifiers into physical spellings (new)
- `backend/app/extractor/variable_extractor_v2.py:1316-1320`. The qualified-column qualifier guard is only `qual.casefold() in _physical_table_names` — no `_is_cte_name`/`_is_derived_alias`/alias check, unlike step 2 (`:1306-1314`).
- `SELECT a.x FROM t1 a; SELECT * FROM A; …` → `a.x` has correct `source_tables=["t1"]` but its `name` is folded to `"A.x"`; L2 field-level fold then false-merges with a real `A.x`.
- **Fix:** mirror step 2's guard and skip scope-local alias/CTE/derived qualifiers; add a collision test.

### M-BM1 — Jaccard node "precision" can exceed 1.0, masking junk nodes (new)
- `backend/tests/test_jaccard_benchmark.py:886-903`. `precision = ni/na` where `ni` counts canonical *entries* not distinct served nodes; merged same-label nodes yield e.g. `8/7 = 1.143`. The `>= 1.0` floor then can't detect an extra junk node (it only lowers 1.143 toward 1.0).
- **Fix:** compute a true set precision (`|{served node realizing ≥1 canonical entry}| / |served nodes|`), or add an explicit extra-node check.

### M-F1 — `scheduleLayoutSave` single-slot coalescing drops concurrent L1/L2 drags (frontend, still open)
- `frontend/src/DataFlowApp.jsx:135-144`. One `pendingLayoutRef` slot + `if (layoutTimerRef.current) return` → an L1 drag followed by an L2 drag within ~1s silently drops the L1 save.
- **Fix:** key pending saves by `(level, script)`.

### M-D1 — Docs still define removed entities / under-specify gate (still open)
- `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md:33,48-50,109,111-112,200-222,321,345` — still promises in-app notifications, full-page login gate, `/api/notifications`, notification bell (removed #293/#322).
- `wiki/DATAFLOW_FORMAL_DEFINITION.md:839-844,865-878` — still defines Open Visit + Notification entities (removed #279/#285/#322).
- `wiki/REQUIREMENTS_TRACEABILITY.md:270,278` — R31.1 "gates every page" (superseded #293); R31.9 "notification store remains" (deleted #322).
- `wiki/SOLUTION_DESIGN.md:1860-1870`, `DATAFLOW_FORMAL_DEFINITION.md:885-888` — gate surface omits `/workspace/{id}/debug/graph`.
- **Fix:** annotate/remove removed-feature prose; add the debug/graph endpoint to the gate list.

### M-D2 — `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:5122-5123` ISSUE-4 "Expected result" stale (new)
- Still promises `a`+`A` → one `a` key (33 fields), but shipped extractor (R-1 `is_alias_handle`) never canonicalizes alias handles — only physical-table attribution collapses.
- **Fix:** reconcile the "Expected result" line with the scope-local alias rule.

### M-D3 — Stale `<meta name="version">` = cache-buster (deploy, still open)
- `backend/app/static/index.html:19` (also `frontend/index.html`, `frontend/dist/index.html`) still `content="3.3.0"`; `frontend/src/api/client.js:3` reads it and appends `?v=3.3.0` to every API call → stale HTTP-cached graph/analysis responses across releases. `deploy.sh` has the stamping step but the committed bundle wasn't produced through it.
- **Fix:** run `deploy.sh` (or inject VERSION) so `3.3.166` lands in the committed `index.html`.

### Carried forward (still open from prior rounds)
- **M-C1 — IDOR on workspace READ endpoints** (`workspace.py:94,219,279,318`; `logs.py:15`): any valid session can read any `ws_id`; only mutations got creator-only checks.
- **M-C2 — Audit log durability** (`workspace_service.py:10` `WORKSPACE_ROOT=/tmp/workspaces`): 0600 fixed perms, but records lost on `/tmp` wipe.
- **M-C3 — Zero-expiry sessions** (accepted #279): stolen tokens live indefinitely.

---

## LOW (open)

### Extractor / L2
- **L-E3 — `_ident_votes` counts non-table identifiers** (`variable_extractor_v2.py:749-757`): alias/column/CTE tokens that case-collide with a physical table also vote, skewing the canonical spelling (spec-compliance only — no wrong merge).
- **L-E4 — `_scope_top` VIEW/CTAS keys not case-folded/statement-indexed** (`:2487-2496`): `VIEW:V` vs `VIEW:v` get distinct buckets; repeated same-name views share one.
- **L-E5 — line-merged self-loop rule drops a line entirely** (`l2_builder.py:1929`): `if non_self or len(self_loops) > 1: continue` → a line whose only edges are `T1→T1` + `T2→T2` emits zero edges (silent data loss). No test for two distinct self-loops.
- **L-E6 — `src <= tgt` TypeError on missing endpoints** (`l2_builder.py:1902-1917`): `parent_of.get(ed.get("source"), …)` → `None` crashes the comparison. Guard/coerce before compare.
- **L-E11 — `_l1_graph_copy` is shallow** (`l1_builder.py:629-640`): nested node/edge dicts shared; memo-protection guarantee incomplete.

### Benchmark
- **L-BM2 — `_flow_covered_by_full` doesn't exclude self-loops** (`test_l2_line_merged_benchmark.py:241-269`): contradicts its own "non-self pair can't be absorbed" premise; fragile coupling to the line-225 fixture.
- **L-BM3 — `_ep_key` uses raw `context`** (`test_l2_line_merged_benchmark.py:110-114`): no `/` split like `_stmt_of_node`; inconsistent/fragile.
- **L-BM4 — doc/comments misstate the metric and `_norm`** (`test_jaccard_benchmark.py:253-258`, `BENCHMARK_CASE_BUILD_METHOD.md:85-86`): recall is bounded ≤1.0 (only node precision isn't); `_norm` folds only the map-key lookup, not the label.

### Frontend
- **L-F1 — `nameFilter.js:32` default `.sort()` is case-sensitive** code-unit order (still open).

### Auth / security (carried)
- **L-S1 — `users.json` written 0644** (`auth_service.py:86`).
- **L-S2 — no test coverage for #303 backoff** (`record_failed_login`/`clear_failed_logins`).
- **L-S3 — session-revocation TOCTOU** in `provision_user(force=True)` (`auth_service.py:27-44`).
- **L-S4 — backoff counters unbounded + shared-IP behind NAT** (`auth_service.py:238-263`).
- **L-S5 — `provision_user` holds lock across 600k PBKDF2** (`auth_service.py:27-39`).
- **L-C1 — CORS `*` with `allow_credentials=True`** (`config.py:24`, `main.py:31-37`).

### Deploy / docs
- **L-D1 — `RELEASE.txt` COMMIT points at `6c9e729`** not the image-building release commit `5cf860f` (provenance ambiguity).
- **L-D2 — `CLAUDE.md:14` "currently 3.3.160"** stale vs 3.3.166.
- **L-D3 — `requirements_v2.md:108`** new L2 line-merged amendment lacks an "IMPLEMENTED — v3.3.166" status marker.

---

## Verified FIXED this round (removed from open list)

- **H-E1** correlated/outer-scope alias resolution → parent-scope chain (`_SelectScope.outer`, `_resolve_alias` walks it); committed `test_walker_gaps_e3.py` now genuinely passes.
- **M-E2** `_scope_top` VIEW/CTAS collapse → `VIEW:{name}`/`CTAS:{name}` distinct buckets.
- **M-E4** `_ident_votes` keyword skew → votes restricted to `VAR`/`IDENTIFIER`.
- **L-E7** benchmark `_norm` masking case → case-preserving fallback (map-key-only fold).
- **L-E8** majority test tie → genuine 3:1 fixture.
- **L-E9** `test_l2_case_merge` keeper pin → asserts lowercase keeper spelling.
- **L-E10** snapshots → re-baselined with no data loss; `EAST5_STZFXXB` filtered view gains correct edges.
- Packaging integrity verified: `VERSION=3.3.166`, `checksums.md5` OK, asset hashes consistent.

---

## Not reviewed

- Full test-suite execution (Python 3.14 sandbox hangs); static analysis only.

---

## LOW-resolution (2026-08-26) — L-E3, L-E4, L-BM4

- **L-E3 — DEFERRED (by design).** `_ident_votes` is built in `__init__`
  (`variable_extractor_v2.py:749-757`) from the raw token stream, deliberately
  independent of the AST walk (which skips ALTER TABLE and other table
  references). There is no table-vs-column/alias/CTE signal available at vote
  time, so a case-colliding non-table identifier can only skew the *display*
  spelling — the vote is consulted solely for names already in
  `_physical_table_names` (via `_canonical_spelling`), and the L2 merge key is
  casefolded, so it never causes a wrong merge (spec-compliance only, as noted).
  A real fix would mean re-deriving table identity from the parse, defeating the
  token-stream majority-vote design. Left as-is.
- **L-E4 — DEFERRED (out of scope for a LOW pass).** VIEW/CTAS inner bodies are
  walked under `VIEW:{name}` / `CTAS:{name}` (`variable_extractor_v2.py:3366/
  3369/3399/3412`) without a statement index or case-folding, so `_scope_top`
  (`:2485-2515`) cannot tell two same-name views apart (their CTE/alias/derived
  registries share one bucket). Fixing it changes the context string stored on
  every var in those bodies, which cascades into L2 dedup keys, graph output,
  cache format, and benchmark results — requiring an `EXTRACTOR_VERSION` bump
  (forbidden for this pass). Case-variant names are self-consistent within a
  statement; only a same-name view *redefinition* leaks scope, an extremely rare
  case. Fold into the next extractor-version change.
- **L-BM4 — FIXED (doc only).** `tools/BENCHMARK_CASE_BUILD_METHOD.md:85-86`
  corrected: `_norm` case-folds only the `NORMALIZE_MAP` key lookup (the
  fallback label preserves source case), not the whole label. The companion
  "a direction may print above 1.0" wording in
  `backend/tests/test_jaccard_benchmark.py` is being reconciled in place by the
  M-BM1 precision fix (parallel agent) and is deliberately left untouched here.
