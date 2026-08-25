# Code Review — R31 multi-user implementation + v3.3.161–164 (open issues only)

> **Reviewed:** 2026-08-24/25 | **Version:** `VERSION` = `3.3.164` | **HEAD:** `863143a`
> **Scope:** `git diff b244871..HEAD` — R31 local-accounts feature (auth, audit, notifications, heavy-gate, login gate, my-workspaces UI), #257/#258 fixes, L2 #288/#289, ~100 new snapshots, playwright E2E.
> **Reviewers:** Codex (read-only — no source modified) via 5 parallel sub-agents: Popper (auth/security), Pasteur (workspace/notification/gate), Sagan (backend fixes), Lovelace (frontend), Galileo (E2E/snapshots/docs).

## Summary

- **3 High** — 2 security (no login rate-limit, hardcoded weak admin password) + 1 doc (traceability summary still says R31 "awaiting go").
- **14 Medium** — security/durability/IDOR, gate bypass, notification concurrency, layout-key bug, stale docs.
- **~25 Low** — hardening, test gaps, stale comments.

No source files were modified. The four prior design HIGHS (A-H1 re-register takeover, A-H2 spoofable identity, A-H3 deletion destroying audit, A-H4 ws-id enumeration) are **all addressed in code**.

---

## Part 1 — R31 auth / identity / security (Popper)

### High

1. **No login rate-limiting or account lockout** — `routers/auth.py:40-61`, `services/auth_service.py:136-160`. `login()` is an unlimited online brute-force oracle; combined with a weak default credential and a known `*@hsbc.com` namespace, credential stuffing is practical. Fix: per-username/IP throttling/lockout with backoff (at minimum exponential delay).
2. **Hardcoded weak default admin credential** — `config.py:39` `PROVISIONED_USERS = {"admin@hsbc.com": "123456"}` is force-synced on every startup when `PROVISIONED_USERS_JSON` is unset. Fix: fail startup if only the placeholder is active outside dev/test; require an explicit secret.

### Medium

3. **`REQUIRE_LOGIN` defaults to false (fail-open) + shared "dev-user"** — `config.py:29`, `routers/workspace.py:42-44`. Forgetting `REQUIRE_LOGIN=1` silently collapses the whole multi-user/audit model to one anonymous identity. Fix: fail loudly or default to production mode.
4. **Per-operation IP is not captured** — `workspace.py:81,128`, `workspace_service.py:245,251` hardcode `ip=""` for all activity/audit writes; only login records IP. Fix: thread `request.client.host` through `_session_ctx`.
5. **No authorization on workspace data endpoints (IDOR among authenticated users)** — `workspace.py:93-103,218-237,278-287,311-336,353-383`, `routers/logs.py:14`. Any valid session can read any `ws_id`'s metadata/activity/export/autocomplete/logs; only layout-put and resume enforce membership. Fix: enforce membership on reads, or document the confidentiality model.
6. **Server-global audit log is not durable (lives in `/tmp`)** — `audit_service.py:33,50-54`, `workspace_service.py:10`. Deletion records are lost on `/tmp` wipe; files are 0644. Fix: persistent volume + restrictive permissions.
7. **Zero-expiry sessions with no revocation** — `auth.py:57-60`, `auth_service.py:136-175`. Stolen token valid indefinitely; password reset doesn't invalidate sessions. Fix: absolute/idle expiry + invalidate on `provision_user(force=True)`.

### Low

- **CORS `*` + `allow_credentials=True`** — `config.py:24`, `main.py:185-191`. Pin `CORS_ORIGINS` to the real frontend origin.
- **Session cookie missing `Secure`** — `auth.py:60`. Set `secure=True` (config-driven) and prefer `__Host-` prefix.
- **PBKDF2 100k iterations + `MIN_PASSWORD_LEN=6` below guidance** — `auth_service.py:42-43`. Raise iterations (or Argon2id) and enforce stronger policy.
- **Username enumeration via response timing** — `auth_service.py:136-144`. Run a dummy PBKDF2 for unknown users.
- **Non-string JSON body → 500** — `auth.py:48-49`, `auth_service.py:90`. Validate/coerce and return 400/401.
- **Over-broad public-prefix matching + public `/docs`/`/openapi.json`** — `main.py:220-234`. Use boundary-safe prefix matching; hide schema in production.

---

## Part 2 — R31 workspace / notification / heavy-gate (Pasteur)

### Medium

1. **`debug_graph_layout` bypasses the heavy-op gate and blocks the event loop** — `routers/dataflow.py:465` (route `:434`). It calls `create_search` directly (no `to_thread`, no `with gate`), so it re-introduces the freeze #273 targeted and breaks the "one heavy op at a time" invariant. Fix: wrap it like `/search`.
2. **Notification writes are RMW over a shared `.tmp` name** — `notification_service.py:39-44,47-59,85-94`. Concurrent writers can drop records/corrupt the file; temp+rename only protects against crash, not concurrency. Fix: NDJSON `O_APPEND` (like `audit_service`) or a per-user lock + unique temp name.

### Low

- **`mark_read` returns 404 on already-read (not idempotent)** — `notification_service.py:85-94`, `auth.py:97-98`. Return 200/no-op for already-read.
- **Empty IP in remove-from-history/create audit records** — `workspace.py:118,81`. Pass `request.client.host`.
- **Creator-delete not crash-atomic; non-creator path can 500 on concurrent delete** — `workspace_service.py:243-253`. Wrap post-audit delete/index steps in try/except; make `_append_record` tolerate a missing parent.
- **`os.write` return value ignored** — `audit_service.py:33`. Loop until fully written (or `open(path,"a")`).
- **users.json RMW has no lock (accepted-loss)** — `auth_service.py:189-244`. Add a `threading.Lock`/file lock so quota/keep-list survive future concurrency.

---

## Part 3 — non-R31 backend fixes (Sagan)

### Verified fixed
- **#257 full-index rebuild** — committed; `index_workspace` always rebuilds from a full scan.
- **D-M2 double scan/parse** — fixed (router threads `tree`+`parsed_cache`).
- **C-H1 L1 sql_text invalidation** — present and correct (exact md5 key + `sql_text` guard, Pass A+B).
- **L2 #288 case-fold merge and #289 write-target routing** — correct.

### Medium

1. **D-M1 still unfixed — bare-SELECT aliases pollute the first source table** — `folder_index_service.py:645-649`. `SELECT NVL(a.bal,0) AS X FROM tab_a` still registers `X` against `tab_a`. Fix: leave plain-SELECT outputs un-attributed or attach to an output container.

### Low

- **Typo-fallback still gated at ≥2 hits** — `folder_index_service.py:1486`. Only short-circuit on exact/prefix hit.
- **MERGE-target script attribution still missing** — `folder_index_service.py:603`. Treat `vt in ("table","merge_target")`.
- **L1 memo miss returns the canonical dict** — `l1_builder.py:678-681`. Return `_l1_graph_copy(result)` on miss too.
- **`_is_physical_ekey` string branch dead/misleading** — `l2_builder.py:366-375`.
- **M4-B empty-cache memo bypass has no test** — `test_l1_memory_reuse.py`.
- **Brittle hardcoded keeper id / `StopIteration` risk** — `test_l2_case_merge.py:32,187`.
- **`_build_script_entry` mutates the shared T1 memo dict** — `multi_script_service.py:82-83`. Copy before mutating.

---

## Part 4 — frontend (Lovelace)

### Medium

1. **`handlePositionsChange` saves L1 drags under the L2 key when L2 is open** — `DataFlowApp.jsx:146-152` (used `:803`/`:871`). The shared callback derives the save key from global `graphLevel`/`currentScriptName`, so dragging an L1 node while L2 is open corrupts the persisted layout. Fix: pass the level explicitly per graph.
2. **Layout-mode switch while L2 flow-only is active re-clips the viewport (D-H2 residual)** — `useCytoscapeGraph.js:375-390`. `relayout()` re-runs layout without showing all elements, so the deferred fit bounds only the closure. Fix: `cy.elements().show()` before layout.

### Low

- **`resolveFlowOnly` still ignores `flow_edge_ids`** — `flowVisibility.js:19-22`.
- **`filterNames` empty-query path unsorted** — `nameFilter.js:31-32`.
- **`gatedFetch` treats any 401 as session expiry** — `client.js:34-41`. Verify backend returns 403 for authenticated-but-forbidden.

### Verified fixed / clean
- **D-H2 initial path** — fixed (fit-then-hide via `onFit` inside deferred timeout).
- **D-M4 `l2Result.full_graph`** — fixed (all L2 entry/exit paths clear it).
- **XSS/injection** — clean (no `dangerouslySetInnerHTML`/`eval`/`new Function`).

---

## Part 5 — E2E / snapshots / docs (Galileo)

### High

1. **Traceability summary block contradicts the R31 section and file title** — `wiki/REQUIREMENTS_TRACEABILITY.md:302-304`. Still says "📝 Design, not implemented | 1 — R31 (awaiting go)", "144 (all)", "Version 3.3.160" while the file title says V3.3.163 and R31.1–29 are ✅. Recount and set version consistently.

### Medium

2. **Individual R31 status markers stale vs shipped code** — `REQUIREMENTS_TRACEABILITY.md:269-285` (R31.4–8, R31.13, R31.15 marked 📝 but implemented).
3. **`requirements_v2.md:320-325` still says "NOT yet implemented … awaits go"** — contradicts the shipped auth/gate/notification code.
4. **`USER_IDENTITY_AND_WORKSPACE_EMAILS.md:5-6,34` header still says "NOT implemented … No code changed"** — self-contradictory with the same block's "all A-H/A-M resolved".
5. **`DATAFLOW_FORMAL_DEFINITION.md:806-830` stale** — still says "only health public", "re-register replaces account", "idle>30min destroys session"; all false post-R31 (#293, #269, #279).

### Low

- **Snapshot repin provenance implicit** — 3 repins (`l2_snapshot_00/02/04`) inside a monolithic release commit with no per-repin note. Add a `SNAPSHOT_CHANGELOG`.
- **Snapshot gate is self-consistency only** — `test_l2_snapshot.py` (now 110 scripts, ~324 subprocess builds × up to 180s). Document one-time human sanity check for new baselines; consider splitting the determinism test.
- **Playwright R2 assertion weakened to `>0`** — `tests/playwright/dataflow.spec.js:114`. Assert a concrete minimum or specific labels.
- **R5 only checks bottom overflow; R6 console listener attached after setup** — `dataflow.spec.js:155-181`.
- **Spec couples to Cytoscape `_cyreg`; `TEST_ZIP` absolute path; stale comment** — `dataflow.spec.js:4,33,52-67`.
- **No E2E for gate/quota** — only unit coverage (`test_r31_gate.py`, `test_r31_auth.py`); the in-app notification subsystem was REMOVED (#322), so it needs no E2E. No browser E2E is planned for gate/quota.
- **Stale "admin bootstrap" comment** — `main.py:200-203`.

---

## Verification method

- 5 read-only sub-agents reviewed disjoint slices in parallel: auth/security, workspace/notification/gate, backend fixes, frontend, E2E/snapshots/docs.
- Static review only (Python 3.14 sandbox can hang on `asyncio.to_thread`/`TestClient`); no full suite run.
- Prior design HIGHS (A-H1–A-H4) and prior round HIGHS (C-H1, D-H2, D-M4, #257, D-M2) explicitly re-checked; statuses recorded above.
- No source files were modified.
