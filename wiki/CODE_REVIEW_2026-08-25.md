# Code Review — 2026-08-25 (v3.3.165 + uncommitted working tree)

**Reviewer:** code-review agent (consolidated from 5 parallel sub-agents)
**Scope:** release `v3.3.165` (commits `fe6e6cc`…`524bdc0`, `VERSION=3.3.165`) **plus** the still-uncommitted working-tree changes (extractor / dataflow / L2 / benchmark / docs).
**Method:** static review only — no source was modified. 5 parallel sub-agents: Security/Auth, Backend dataflow/extraction, Frontend, Docs/traceability, E2E/deploy.

---

## Verdict (read this first)

1. **Do not merge the uncommitted extractor change as-is.** Removing the script-global alias fallback breaks correlated subquery / outer-scope alias resolution (H-E1) — it fails an already-committed test and corrupts `tpcds_qualified` corpus results. Two further cross-scope contamination bugs (M-E2, M-E3) sit in the same change.
2. **v3.3.165 security hardening is largely correct** (many prior findings verified fixed), but it introduces one new HIGH self-DoS (H-S1) and still leaves the weak default admin credential (H-S2).
3. **Frontend has one real HIGH** (H-F1): the "Flow only" toggle can render ON while showing the full graph.
4. **Docs are badly stale** — the v3.3.164 docs recorded the batch as "awaiting GO", then v3.3.165 shipped it with no docs pass. 5 High + 5 Medium documentation contradictions below.

---

## HIGH (open)

### H-E1 — Extractor: removed global alias fallback breaks correlated subqueries (uncommitted)
- `backend/app/extractor/variable_extractor_v2.py:2437-2454` (`_resolve_alias`); global `self._table_aliases` removed.
- `_resolve_alias` now resolves only through `scope.aliases`, but nested `SELECT`/`EXISTS`/`IN (…)` bodies get a fresh `_SelectScope` with **no parent-scope chain**. A correlated outer alias (`o.order_id` inside `NOT EXISTS (… WHERE p.order_id = o.order_id)`) now resolves `o` → `"o"` instead of `orders`, setting `source_tables=["o"]` and writing phantom evidence into `_script_schemas`.
- **Breaks committed test** `backend/tests/test_walker_gaps_e3.py::test_update_where_and_not_exists_subquery_walked` (asserts `o.order_id` in `TOP0/exists1` has `source_tables == ["orders"]`) and real corpus scripts (`samples/tpcds_qualified/69.sql`).
- **Fix:** thread the enclosing scope into nested walks (`_walk_select`/`_walk_setop` take a `parent_scope`), and make `_resolve_alias` walk a parent-scope chain. Do **not** restore the flat last-write-wins map (that reintroduces the cross-statement aliasing bug this change was fixing).

### H-S1 — Login backoff `time.sleep()` blocks the async event loop → unauthenticated self-DoS (committed)
- `backend/app/routers/auth.py:65` (`time.sleep(auth_service.record_failed_login(...))`) inside `async def login` (`:42`), plus `auth_service.py:57` `_PBKDF2_ITERATIONS = 600_000` run synchronously via `auth_service.login()`.
- `/api/auth/login` is gate-exempt (public). Each failed attempt runs a 600k-iteration PBKDF2 **and** then a blocking `time.sleep` (up to 5s) on a single-worker uvicorn loop. A handful of concurrent failed logins stalls the whole service (health + authenticated API included) — an availability DoS that requires no valid credentials.
- **Fix:** `await asyncio.sleep(...)` for the backoff, and run credential verification off-loop (`await asyncio.to_thread(auth_service.login, ...)`), keeping counter updates under the existing lock.

### H-F1 — Edge-only flow closure: toggle ON but full graph rendered (committed)
- `frontend/src/utils/flowVisibility.js:22-27` vs `:61-64`. `resolveFlowOnly` returns `true` for an edge-only closure (`flow_edge_ids` non-empty, `flow_node_ids` empty), but `applyFlowVisibility` short-circuits on `!Array.isArray(flowNodeIds) || flowNodeIds.length === 0` and calls `cy.elements().show()`.
- Result: "Flow only" toggle renders ON (`DataFlowGraph.jsx:289-295`, seeded via `DataFlowApp.jsx:215`) while the graph shows **everything**. Contradicts the documented contract ("edge-only closure must still enable View 1").
- **Fix:** when `flowOnly` && node list empty && edge list non-empty, derive the visible node set from the closure edges' `source`/`target` ids, then show those endpoints + closure edges. Add an `applyFlowVisibility` test for that case.

### H-S2 — Hardcoded weak default admin credential (still open, prior round)
- `backend/app/config.py:42` — `{"admin@hsbc.com": "123456"}`, force-synced each startup. Rate limiting (#303) now exists, but the default is still guessable on the first attempt.
- **Fix:** provision the admin from an env secret with a generated/strong password, or force a first-login change.

### H-D1 — `requirements_v2.md:71` says "implementation queued, awaiting GO" (committed code)
- The whole code-review-decision batch (access model, security hardening, notification removal #322, layout fixes) is shipped in v3.3.165, but the amendment header still reads "queued, awaiting GO".
- **Fix:** rewrite header to "IMPLEMENTED (v3.3.165, 2026-08-25)" and convert each bullet to shipped/verified past tense.

### H-D2 — `wiki/REQUIREMENTS_TRACEABILITY.md:303-320, 328` — 11 tasks marked ⏸ but implemented
- The "code-review decisions (2026-08-25)" table lists all 11 tasks as pending/Awaiting-GO; all are in v3.3.165.
- **Fix:** flip rows to ✅ with v3.3.165 reference; drop the "Awaiting GO" summary.

### H-D3 — `wiki/REQUIREMENTS_TRACEABILITY.md:22 (R1.8), :271 (R31.2)` — "partial" rows describe gaps already closed
- R1.8 (derived-alias leak / #308) and R31.2 (empty per-op IP / M-Po4) are both fixed in v3.3.165, yet both rows still claim a live leak. Summary counts ("2 partial") are wrong.
- **Fix:** flip both to ✅; recount summary (169 → 171).

### H-D4 — `wiki/REQUIREMENTS_TRACEABILITY.md` still says V3.3.164
- Title (`:1`), narrative (`:4`), and summary version (`:329`) are 3.3.164; `VERSION`/`RELEASE.txt` are 3.3.165.
- **Fix:** bump to 3.3.165.

### H-D5 — `wiki/SOLUTION_DESIGN.md:1807-1876` — R31 section still "awaiting go / no code changed"
- Still describes the pre-implementation design: notification inbox, "self-register", "re-register" recovery, 30-min idle TTL, `open_visits`, `/api/notifications`, login entrance page + notification bell — all removed/changed by #269/#279/#285/#293/#322.
- **Fix:** mark superseded and point to `R31_IMPLEMENTATION.md` + `USER_IDENTITY_…`, or rewrite to the shipped model.

---

## MEDIUM (open)

### Extractor (uncommitted)
- **M-E2 — `_scope_top` collapses `VIEW:`/`CTAS:` into one scope key** (`variable_extractor_v2.py:2405-2421`). Two `CREATE VIEW` statements share one CTE registry bucket, so a CTE `foo` in view #1 makes physical `foo` in view #2 look like a CTE. Fix: key by full statement identity (`VIEW:{name}`), not a bare kind prefix.
- **M-E3 — `_canonicalize_table_names` rewrites CTE-sourced `source_tables`** (`:1262-1266`). A local CTE `foo` whose casefold collides with a physical `FOO` elsewhere gets silently re-labeled to the physical canonical spelling — cross-scope attribution corruption. Fix: only canonicalize entries known physical for that variable's scope (skip CTE/derived entries).
- **M-E4 — `_ident_votes` counts SQL keywords** (`:718-724`). Only STRING/NUMBER tokens are excluded; keyword tokens (SELECT/FROM/…) vote under their casefold, so a table named `order`/`user`/`group` gets a keyword-skewed canonical spelling. Fix: restrict votes to identifier token types.

### Frontend
- **M-F1 — `DataFlowApp.jsx:135-143` single-slot layout-save coalescing.** L1 and L2 are now mounted side-by-side (#309), but `scheduleLayoutSave` uses one `pendingLayoutRef` slot; two drags in the same debounce window overwrite each other and one edit is silently dropped. Fix: key the pending buffer by `(level, script)`.

### E2E / deploy
- **M-T1 — `tests/playwright/dataflow.spec.js:190-192` "top overflow" math uses table center as the top edge.** Cytoscape `position()` is the node center; correct edges are `center ± _tableHeight/2`. As written, any ≥2-field table falsely flags "top overflow". Passes today only because default flow-only L2 shows ~1 field/table. Fix: compute `top = cy - ph/2`, `bottom = cy + ph/2`.
- **M-T2 — `dataflow.spec.js:199-205` R6 no longer drives search/openL2/tap.** It only asserts console errors from `beforeEach`, silently narrowing coverage (L1/L2/edge-tap console errors are no longer checked). Fix: have R6 exercise the full debugger flow again, or assert console errors in the tests that actually perform those actions.

### Docs
- **M-D1 — `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md` body contradicts shipped code** (`:33,48-50,109,111-112,213-222,321,345`). Header claims "reflects the shipped code" but body still promises in-app notifications, a full-page login gate, `/api/notifications`, notification bell — all removed (#293/#322).
- **M-D2 — `wiki/DATAFLOW_FORMAL_DEFINITION.md:839-844,865-878`** still defines Open Visit (idle expiry), Activity "visit start/end", a `notifications/{username}.json` entity, and "creator alerted in-app" — entities #279/#285/#322 deleted.
- **M-D3 — `REQUIREMENTS_TRACEABILITY.md:270 (R31.1), :278 (R31.9)`** requirement text not reconciled: R31.1 still says "gates every page" (superseded by #293/R31.15); R31.9 says notification store "remains" (deleted by #322).
- **M-D4 — `REQUIREMENTS_TRACEABILITY.md:4` vs `:326-327`** conflicting partial counts ("1 partial" in header, "2" in summary).
- **M-D5 — `SOLUTION_DESIGN.md:1860-1870`, `DATAFLOW_FORMAL_DEFINITION.md:885-888`** gate surface omits `/workspace/{id}/debug/graph` (now gate-wrapped by M-P1).

### Carried forward (still open from prior rounds)
- **M-C1 — IDOR on workspace READ endpoints** (`workspace.py:94,219,279,318`; `logs.py:15`). Any valid session (or anonymous with gate off) can read any `ws_id` data; only mutations got creator-only checks.
- **M-C2 — Audit log durability** (`workspace_service.py:10` `WORKSPACE_ROOT=/tmp/workspaces`). 0600 fixed permissions, but records are still lost on `/tmp` wipe.
- **M-C3 — Zero-expiry sessions** (accepted design #279). Revocation-on-password-change added, but stolen tokens live indefinitely (no absolute/idle expiry).

---

## LOW (open)

### Auth / security
- **L-S1 — `auth_service.py:86` `users.json` written 0644.** Holds PBKDF2 hashes/salts + `last_login_ip`; inconsistent with the 0600 audit fix. Fix: `mode=0o600` + `os.chmod` after rename.
- **L-S2 — No test coverage for the new #303 backoff** (`record_failed_login`/`clear_failed_logins`/`_backoff_delay` untested). Fix: unit-test the delay sequence + reset-on-success.
- **L-S3 — Session-revocation TOCTOU in `provision_user(force=True)`** (`auth_service.py:27-44`): revoke happens after releasing `_users_lock`; a racing login can re-verify the old hash and mint a session post-revoke.
- **L-S4 — Backoff counters unbounded + shared-IP behind NAT** (`auth_service.py:238-263`): no time-window/decay; one shared `request.client.host` throttles all users. Fix: time-windowed buckets + document forwarded-IP requirements.
- **L-S5 — `provision_user` holds `_users_lock` across 600k PBKDF2** (`auth_service.py:27-39`). Fix: hash before acquiring the lock.

### Extractor / L2 (uncommitted)
- **L-E5 — `l2_builder.py:1922-1930` line-merged self-loop rule can drop a line entirely** (two self-loops `T1→T1`,`T2→T2` with no cross pair → zero merged edges). Fix: keep self-loops for tables absent from non-self pairs + add a test.
- **L-E6 — `l2_builder.py:1917` `src <= tgt` can raise TypeError on missing endpoints.** Fix: skip/coerce edges with None/empty `source`/`target`.
- **L-E7 — `test_jaccard_benchmark.py:358-360` `_norm` casefolds everything**, masking case regressions in the precision/recall gate. Fix (if not intended): fold map keys only.
- **L-E8 — `test_variable_extractor.py::test_mixed_case_table_folds_to_majority_spelling`** asserts a 2:2 tie-break, not a true majority (docstring says "2 vs 1"). Fix: make the fixture a genuine 3:1 majority or rename to tie-break semantics.
- **L-E9 — `test_l2_case_merge.py:34-47`** no longer pins *which* occurrence wins the merge (`keep["id"] == keeper_id` is tautological). Fix: assert keeper `table_name` is the canonical lowercase spelling.
- **L-E10 — `test_l2_snapshot.py` baselines likely stale vs uncommitted canonicalization.** Fix: re-baseline only after H-E1/M-E3, with human diff review.
- **L-E11 — `l1_builder.py:629-640` `_l1_graph_copy` is shallow** (nested node/edge dicts shared), so the memo-protection guarantee is incomplete. Fix: deep-copy or enforce the no-mutation contract.

### Frontend
- **L-F1 — `utils/nameFilter.js:32` default `.sort()` is case-sensitive code-unit order**, despite the "matching backend sorted keys" comment. Fix: case-insensitive comparator.
- **L-F2 — `DataFlowApp.jsx:805` `refitKey={graphLevel}` is a dead prop** (never destructured in `DataFlowGraph`). Fix: wire it or remove it.
- **L-F3 — `flowVisibility.test.js:79-81`** tests only `resolveFlowOnly`; no `applyFlowVisibility` edge-only test (masks H-F1). Fix: add it.
- **L-F4 — `nameFilter.test.js:35`** mirrors the implementation over a 6-element fixture; doesn't exercise the cap or pin alphabetical contract.

### E2E / docs
- **L-T1 — `backend/app/static/index.html:19` `<meta name="version" content="3.3.0">` stale** (VERSION=3.3.165).
- **L-T2 — `tools/BENCHMARK_CASE_BUILD_METHOD.md:60`** route prefix wrong (`/views/{id}/level2` → `/workspace/{ws_id}/views/{view_id}/level2`).
- **L-T3 — `BENCHMARK_CASE_BUILD_METHOD.md:94`** "every feature, both directions" wording drifts from `FLOORS[seed][feat][recall|precision]`.
- **L-T4 — `BENCHMARK_CASE_BUILD_METHOD.md:121-124`** line-merged benchmark underspecified (no case type/fixture for `flow_only_merged`/`full_merged`).
- **L-D1 — `REQUIREMENTS_TRACEABILITY.md:22`** D-M1 line ref `folder_index_service.py:646-650` points at the wrong guard (was ~619-624, now removed).
- **L-D2 — `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:5181/5213/5242`** ISSUE-4/5/6 statuses stale ("no-source-changes"/queued) though the tree implements them; also makes traceability R32.1-3 (`:299-301`) stale.
- **L-D3 — `BUG_ANALYSIS_AND_SUGGESTIONS.md:5181`** ISSUE-4 pre-fix line refs drifted ~150 lines after the fix.
- **L-C1 — CORS `*` with `allow_credentials=True`** (`config.py:24`, `main.py:31-37`) unchanged (prior round).

---

## Verified FIXED this round (brief — not open)

- Notification removal (#322) complete across backend + frontend + served bundle; tests assert 404/405.
- `REQUIRE_LOGIN` fail-open default → now `"true"` (conftest forces off).
- Per-operation IP capture (M-Po4, #316), creator-only mutation authz (#317), audit `0o600` + full-write loop (#318), session revocation on password reset (#319).
- `debug_graph_layout` now heavy-gate-wrapped (M-P1).
- D-M1 bare-SELECT alias pollution (#308), layout drag level (#309), layout re-clip (#310), plus ~10 prior Lows — all fixed.

## Not reviewed (out of scope)

- No full test-suite execution (Python 3.14 sandbox hangs on TestClient); findings are static-analysis only.
- Docker parts/checksums were verified consistent (`md5sum -c` OK; static bundle byte-identical to repo).
