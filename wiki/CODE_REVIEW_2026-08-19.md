# Code Review — Multi-user local-account requirement + v3.3.159 source (open issues only)

> **Reviewed:** 2026-08-19 | **Version:** `VERSION` = `3.3.159` | **HEAD:** `f1de528`
> **Scope:** `git diff 2a210e0..HEAD` — the new multi-user / local-account (no email) design docs, plus the v3.3.159 source changes (search cache reuse, flow-cone recolor, edge-hover tooltip removal) and the new line-count ledger/deploy scripts.
> **Reviewers:** Codex (read-only — no source modified) via 6 parallel sub-agents: Herschel (design note), Hooke (requirements/traceability + doc↔code), Locke (solution design/formal definition), Heisenberg (backend), Schrödinger (frontend), Faraday (deploy/tooling).
> **Primary documents:** `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md` (new), `requirements_v2.md`, `wiki/REQUIREMENTS_TRACEABILITY.md`, `wiki/SOLUTION_DESIGN.md`, `wiki/DATAFLOW_FORMAL_DEFINITION.md`.

## Summary

- **6 High** — 4 identity/audit/access design flaws + 1 doc/code contradiction + 1 backend cache-invalidation defect.
- **20 Medium** — 15 document issues, 5 source/tooling issues.
- **~28 Low** — wording, test-coverage gaps, robustness, stale references.

No source files were modified. The multi-user feature is documentation-only (no code landed); v3.3.159 source is the cache-reuse + flow-cone/tooltip changes.

---

# Part A — Multi-user local-account design (documents)

## High

### A-H1 · Password “re-register” is an unauthenticated account takeover
- **File:** `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md` §5.1:98–101, §8:246–247, §10.10:286.
- **Problem:** “Re-register” recreates any existing `*@hsbc.com` username with a new password and replaces the record with no proof of ownership. Since `creator_username` is just the username string, the attacker inherits creator-delete rights over that user’s workspaces.
- **Fix:** remove self-service re-register; require admin-mediated reset or a pre-shared second factor; never let “forgot password” overwrite an existing identity.

### A-H2 · Self-registration makes audit identity self-asserted
- **File:** §1.2, §5.1:92–93, §9:260.
- **Problem:** any user can claim any unregistered colleague name as a username, so “who modified this is always answerable” is false — the core audit goal is undermined.
- **Fix:** pre-provision accounts from an allowlist/directory (reject unknown usernames) or require admin approval.

### A-H3 · Workspace deletion destroys its own audit trail
- **File:** §5.4:143 vs §5.6:186–188.
- **Problem:** “workspace deleted” is listed as an activity-log event, but physical delete removes `activity.json` with the workspace — so who deleted it is not durably recorded.
- **Fix:** write the deletion event to a server-global/audit log (or the deleter’s notifications) before removing the directory.

### A-H4 · Workspace-id guessing/enumeration is unaddressed
- **File:** §3:63–65, §9:260–261.
- **Problem:** open-by-id is accepted as “loose access”, but the note never specifies id entropy/generation; sequential ids make the whole namespace enumerable by any logged-in user.
- **Fix:** state `ws_id` is high-entropy (UUID4/128-bit random) and add no listing/all-ids endpoint.

## Medium

### A-M1 · Near-identical DELETE paths for two very different operations
- **File:** §7:226–227. `DELETE /api/workspace/{ws_id}` (physical delete) vs `DELETE /api/workspaces/{ws_id}` (remove-from-list). Fix: rename the latter to `/api/me/workspaces/{ws_id}`.

### A-M2 · Quota limits index entries, not workspaces/server space
- **File:** §5.6:179–183, §10.9:287–288. `MAX_WORKSPACES_PER_USER` counts “my workspaces” rows only; a creator can make unbounded workspaces by removing old rows. Clarify intent or enforce the cap on creations.

### A-M3 · “activity.json append-only (no read-modify-write)” contradicts “temp + rename”
- **File:** §6:204–207. Appending to a JSON array via temp+rename is read-modify-write, and concurrent appends can silently drop audit entries. Use `O_APPEND` per-record writes (or one entry per file), or document RMW + a per-workspace lock.

### A-M4 · “monotonically increasing state_version” conflicts with accepted lost updates
- **File:** §5.3:124–126, §6:204. Two writers can both write N+1; the loser’s change is dropped but version stays N+1, so the “state changed by X” notice may never fire. Base the notice on a CAS/lock, mtime/hash, or drop the monotonic claim.

### A-M5 · Layout storage is incoherent
- **File:** §5.3:133–139, §6:197, §7:233. `meta.json` is said to hold `node_positions`, `views.json` “stays”, but autosave is `PUT /api/workspace/{ws_id}/views/{view_id}/layout` and L1 has no `view_id`. Define one storage location and the L1/L2 view-id scheme.

### A-M6 · No workspace-create endpoint is defined
- **File:** §7:237. The table says “Workspace create records creator_username…” but no `POST /api/workspace` exists; id generation/creator assignment unspecified. Add the endpoint and its id rule.

### A-M7 · CSRF and cookie attributes are missing
- **File:** §9:264, §3:63. Only `HttpOnly` is mentioned; no `SameSite`, no CSRF protection for cookie-authenticated state-changing endpoints (logout/delete/layout/search), and traffic is plain HTTP. Add `SameSite`, a CSRF token or same-origin check, and document the HTTP residual risk.

### A-M8 · Single-worker assumption is not a stated deployment constraint
- **File:** §6:205, §10.16:294. In-memory sessions/open_visits and the concurrency acceptance only hold with one uvicorn worker. Enforce/document `--workers 1`, or move to shared durable storage.

### A-M9 · Restart loses open-visit flush
- **File:** §5.2:117, §6:200. `open_visits` is in-memory; a restart drops active visits without the promised visit-end memos/creator alerts. Accept explicitly, or persist/flush at startup.

### A-M10 · open_visits keyed by username conflates multiple sessions
- **File:** §5.2:109–116, §6:200. Logging out of one browser “flushes all open visits” for the user, killing other browsers’ visits and double-writing memos. Key by session token and aggregate per user at flush.

## Low

- **A-L1 · IP is login-time, not per-operation** (§5.1:102 vs §4:67) — read `request.client.host` per operation.
- **A-L2 · No login rate-limit/lockout** (§5.1/§9).
- **A-L3 · min password length 6 is weak** (§9:260, §10.3:277) — combined with no lockout.
- **A-L4 · memo content vs “no script contents”** (§5.4:154–158 vs Q7:77) — define exactly which fields are excluded.
- **A-L5 · long search can expire the 30-min session mid-request** (§5.2:113–114) — touch `last_active` during long ops.
- **A-L6 · “closes last wins” misstates the rule** (§4 Q2:71) — winner is the last *writer*, not the tab that closes last. Reword to “last write wins”.
- **A-L7 · plain-HTTP transport** (§3:63, §9:264) — document the LAN-only residual risk.

---

# Part B — Requirements / traceability doc↔code consistency (v3.3.159)

## High

### B-H1 · Edge-hover tooltip is “NOT yet implemented” but the code already removed it
- **File:** `requirements_v2.md:301`.
- **Problem:** the amendment says “recorded 2026-08-14; NOT yet implemented”, but commit `a77dfdd` deleted `edgeHover` + `.edge-tooltip` from `DataFlowGraph.jsx` and `onEdgeHover`/`onHoverLeave` from `useCytoscapeGraph.js`.
- **Fix:** mark implemented (v3.3.159) and describe the removal, or (if deferring was intended) revert the code.

## Medium

- **B-M1 · R4.5/R28.3 still assert the tooltip exists** — `wiki/REQUIREMENTS_TRACEABILITY.md:52,226`. Mark removed/deprecated and cross-reference the amendment.
- **B-M2 · New amendments lack traceability rows** — `wiki/REQUIREMENTS_TRACEABILITY.md` (after R30.5). The cache-reuse and tooltip-removal amendments have no matrix rows; Summary counts not updated.
- **B-M3 · R30 status stale** — `wiki/REQUIREMENTS_TRACEABILITY.md:246,271`. Flow cone is implemented but R30 still 📝 “Design, not implemented”.
- **B-M4 · “uniform style + mid-point arrow” still “NOT implemented”** — `requirements_v2.md:104`, but `L2_UNIFORM_EDGE_STYLES`/`mid-target-arrow-shape` exist in `graphStyles.js:1036-1055`.
- **B-M5 · “File 1 ignored for scope” is overstated** — `wiki/SOLUTION_DESIGN.md:1733-1737`, `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:4931-4936`. Code preserves File-1 scope when File 2 is absent (`filter_service.py:285-286`). Reword: File 2 is sole scope source only when present; File-1-only preserved.

## Low

- **B-L1 · pivot class mislabeled** — `requirements_v2.md:61` says `edge-selected`; the applied class is `flow-cone-pivot` (also in `DATAFLOW_FORMAL_DEFINITION.md:251`).
- **B-L2 · wrong test path** — `requirements_v2.md:284` says `tests/test_l1_cache_aware.py`; it’s `backend/tests/test_l1_cache_aware.py`.
- **B-L3 · multi-user (R31) absent from requirements_v2 + README** — traceable only in the traceability matrix.
- **B-L4 · username regex tightened without authorization** — `DATAFLOW_FORMAL_DEFINITION.md:813-814` (`^[A-Za-z0-9._%+-]+@hsbc\.com$`) is stricter than the locked `*@hsbc.com`; promote the exact regex to the note or defer the charset.
- **B-L5 · formal definition omits login gate + ≤1s layout cadence** — `DATAFLOW_FORMAL_DEFINITION.md:806-877`.
- **B-L6 · stale “no automated L1 check”** — `wiki/SOLUTION_DESIGN.md:1520-1522` (BUG_ANALYSIS cites the wrong line `1488-1490`).
- **B-L7 · meta.json vs views.json state-split ambiguity** — `DATAFLOW_FORMAL_DEFINITION.md:836-842` vs `SOLUTION_DESIGN.md:1810-1811`. Clarify: `meta.json` = last-search ref + opened-L2 registry + node positions; payloads stay in `cache/views.json`.
- **B-L8 · stale anchors + cache-key wording** — `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:4925,4942`, `SOLUTION_DESIGN.md:1746`: key uses `rel_path`, not `script_name`.
- **B-L9 · API list omits workspace-create + `/search` heavy-op gate** — `SOLUTION_DESIGN.md:1849-1853`.

---

# Part C — Source code review (v3.3.159 + new tooling)

## High

### C-H1 · L1 cache reader is key-agnostic — edited scripts can be served stale analysis
- **File:** `backend/app/services/l1_builder.py:505-522` (acceptance at `:569-571`).
- **Problem:** the reader globs every `analysis_*.json` and maps by `script_name`, validating only `extractor_version` — not `sql_text`. After an edit + re-index, the old versioned-but-different-sql file survives, and the hit is accepted, yielding wrong lineage for the current on-disk SQL. (The claimed “mirror of `dataflow_service`” is wrong: that path reads the exact sql-keyed cache.)
- **Fix:** compute the exact key `md5(EXTRACTOR_VERSION|name|sql)[:12]` and read `analysis_{key}.json` directly (as `dataflow_service` does), or at minimum reject when `analysis.get("sql_text") != sql`.

## Medium

- **C-M1 · Pass B lacks the extractor-version guard** — `l1_builder.py:601-609`. Pass A has it; Pass B builds `model_by_script` from possibly-stale cache → graph/model divergence. Move the guard into `_lookup_analysis` so both passes share it.
- **C-M2 · byte-identity test compares raw vs S4b-mutated cache** — `backend/tests/test_l1_cache_aware.py:57-83`. It only proves the invariant for S4b-invariant samples; build the “fresh” baseline from the same post-index dict and add version-mismatch + edited-script tests.
- **C-M3 · `excluded()` tests absolute path** — `tools/line_count_full.py:47-51`. An ancestor dir named `static/dist/docker_image/…` excludes everything and the report silently comes back empty. Use `relpath(…, ROOT)`.
- **C-M4 · UTF-8 boundary misfire** — `tools/line_count_full.py:65`. `head.decode("utf-8")` on the first 8192 bytes can raise mid-multibyte and skip a valid file. Decode with `errors="ignore"` or check for NUL only.
- **C-M5 · hardcoded output path** — `tools/render_ledger_full.py:12`. `OUT` is `/home/huangyf/…`; derive from `__file__`.

## Low

- **C-L1 · single-script path still re-extracts** — `l1_builder.py:525-556` bypasses the cache (`len(script_data) < 2`).
- **C-L2 · no negative test for tooltip removal** — `DataFlowGraph.test.jsx:68-79`. Assert `.edge-tooltip` absent and hook options undefined.
- **C-L3 · release note says “pivot class” changed, but class is still `flow-cone-pivot`** — `graphStyles.js:1024` (color only).
- **C-L4 · line count ≠ `wc -l`** — `line_count_full.py:71-73` (logical records vs newline count); footer claims `wc -l` match.
- **C-L5 · `tot_funcs` mixes areas** — `render_ledger_full.py:212`; `src_funcs` computed but unused.
- **C-L6 · `rel.rsplit("/",1)[1]` IndexError for root-level files** — `render_ledger_full.py:158`.
- **C-L7 · only catches SyntaxError/UnicodeDecodeError** — `line_count_full.py:265-269`; add `OSError`.
- **C-L8 · misleading docstring/dead import** — `line_count_full.py:11-12,22-23`.
- **C-L9 · JS/JSX scanner not comment-aware** — `line_count_full.py:129-204`; label output approximate.
- **C-L10 · `HOST_PORT` unquoted/unvalidated** — `target_deploy.sh:55,165,184`.
- **C-L11 · version guard checks VERSION only; COMMIT stale** — `target_deploy.sh:68-84`.
- **C-L12 · relative LOG_FILE splits logs** — `target_deploy.sh:10-13,93`.

---

## Verification method

- 6 read-only sub-agents reviewed disjoint slices in parallel (3 docs, 3 source).
- Static review only (Python 3.14 sandbox can hang on `asyncio.to_thread`/`TestClient`); no full suite run.
- Doc↔code claims (tooltip removal, cache-key handling, File-1/File-2 scope) cross-checked against HEAD by the agents.
- No source files were modified.

---

# Part D — v3.3.160 source update (added 2026-08-20/21)

> **Scope:** `git diff f1de528..HEAD` (v3.3.160: L2 two-view field-flow toggle, case1 autocomplete, index full-rebuild) + uncommitted working-tree changes.
> **Reviewers:** 4 parallel sub-agents — Maxwell (backend), Avicenna (frontend), Copernicus (router/deploy), Hume (snapshots/samples/docs).

## Verified fixed

- **C-H1 (stale-analysis cache bug) is FIXED** — `l1_builder.py:515-551` adds `_analysis_current()` (checks `extractor_version` **and** `sql_text`) and an exact `md5(EXTRACTOR_VERSION|name|sql)[:12]` key read, applied to both L1 passes. Stale-by-name analysis is rejected.
- `--noproxy '*'` is correct in `release.sh:49` and `target_deploy.sh:184,210`.

## High

### D-H1 · #257 full-rebuild fix is uncommitted — absent from the v3.3.160 release
- **File:** `backend/app/routers/workspace.py:106-110` (working tree only); `backend/tests/test_index_full_rebuild.py` (untracked).
- **Problem:** committed HEAD (`b244871`) and release `9bcfe28` still use `scripts = body.get("scripts", [])`, so a caller-supplied subset can overwrite `cache/table_index.json` and silently shrink search coverage. The fix and its regression test exist only in the working tree and would fail against the release tree.
- **Fix:** commit the router change + test into a commit reachable from the release tag (re-tag/cherry-pick before shipping).

### D-H2 · Flow visibility is applied before the deferred `cy.fit` — View 2 renders clipped
- **File:** `frontend/src/hooks/useCytoscapeGraph.js:245-251,292-295`; `frontend/src/utils/layoutCore.js:218-224`; `frontend/src/components/DataFlowGraph.jsx:236-237`.
- **Problem:** `applyFlowVisibility` runs synchronously after layout, but `cy.fit()` is deferred via `setTimeout(…,100)`; the later fit sees only the visible closure (display:none elements are excluded), so the viewport fits the hidden subset. Toggling to full (View 2) renders non-closure nodes off-screen until the user presses Fit.
- **Fix:** fit the full graph before hiding (e.g. resolve the deferred fit via callback/promise, then call `applyFlowVisibility`), and gate mount-time `relayout` on `layoutDoneRef`.

### D-H3 · Hardcoded plaintext sudo password (pre-existing)
- **File:** `deploy.sh:51` (`echo huangyf | sudo -S …`). Replace with a NOPASSWD sudo rule for the specific command or prompt interactively.

## Medium

- **D-M1 · bare-SELECT output aliases pollute the first source table** — `folder_index_service.py:625-632`. `SELECT NVL(a.bal,0) AS X …` attributes `X` to the source table's field list, causing false field↔table associations. Leave output aliases un-attributed (or use an explicit output container).
- **D-M2 · index call parses the workspace twice** — `backend/app/routers/workspace.py:112-113`. Router `scan_folder` + `index_scripts`→`_collect_schema_files`→`scan_folder` re-read/re-parse every `.sql`. Thread a `parsed_cache` through to keep the "one parse per script" optimization.
- **D-M3 · `deploy.sh` health curls still lack `--noproxy`** — `deploy.sh:55,57`. Same failure mode that `f1c79a9` fixed elsewhere; add `--noproxy '*'`.
- **D-M4 · `l2Result.full_graph` not cleared on delete/open** — `DataFlowApp.jsx:615` (with `:346,:397,:243`). Since `full_graph` is the primary render source, deleting a workspace/view or opening a new L2 leaves the previous script's graph + stale header/toggle. Reset `setL2Result(null)`/`setFlowOnly(null)` alongside `setL2Graph(null)`.
- **D-M5 · snapshot coverage silently drops 08/09 scripts** — `backend/tests/test_l2_snapshot.py:45`. New samples pushed `tpcds_qualified/08.sql`+`09.sql` past `MAX_SCRIPTS=12`; their snapshots were deleted. Raise the cap or document the unpinning.
- **D-M6 · OCR sample RFN has dangling `AND` predicates** — `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql:818,770`. Not valid on a real engine (only the lenient extractor passes). Fix to valid SQL or mark as a "known-invalid OCR fragment".
- **D-M7 · R30.8 description mismatches the implementation** — `wiki/REQUIREMENTS_TRACEABILITY.md:254`. It says "target-field highlight toggle between two open L2 views"; the code is a single View-1-flow-only ↔ View-2-full visibility toggle. Reword.
- **D-M8 · docs reference an untracked review file** — `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md:7`, `wiki/REQUIREMENTS_TRACEABILITY.md:260` cite `wiki/CODE_REVIEW_2026-08-19.md`, which is untracked (`??`). Commit it or inline the findings.

## Low

- **folder_index_service.py:1466** — typo fallback never runs when ≥2 substring hits, even if none is the intended name.
- **dataflow_service.py:660-696** — matched L2 response can emit `flow_node_ids`/`flow_edge_ids` without `full_graph` when the second build errors.
- **folder_index_service.py:570-632** — MERGE (`merge_target`) tables get output-alias fields but not script attribution; unify table/merge_target registration.
- **nameFilter.js:32** — empty-query branch claims alphabetical but returns insertion order; sort or fix the comment.
- **flowVisibility.js:19-21** — `resolveFlowOnly` keys on `flow_node_ids` alone, ignoring `flow_edge_ids`.
- **DataFlowApp.jsx:466 / FolderTree.jsx:33** — script selection change never re-indexes; the removed stale/Re-index UI was the only (dead) recovery path.
- **workspace.py:88** — `body: dict` still required though its `scripts` value is ignored; make optional.
- **deploy.sh:38 / fast_deploy.sh:13** — `$VERSION` unescaped in `sed` replacement (`&`/`\`/`|` risk).
- **deploy.sh:39 / fast_deploy.sh:14** — `grep` treats `$VERSION` as a regex; use `grep -F`.
- **deploy.sh:38 / fast_deploy.sh:13** — `sed -i -E` is GNU-specific (BSD/macOS breaks).
- **samples RFN** — many `CASE WHEN/THEN` branches hand-collapsed to "legible ELSE value" (not verbatim OCR); mark as placeholders.
- **samples EAST5_STZFXXB_M.sql:138,74** — `NVL_WS(...)` likely `NVL(...)`; `REPLACE("$(load_date)",…)` double-quoted var; verify against source.
- **requirements_v2.md:290** — stale "858 passed / 5 skipped" full-suite count vs v3.3.160.
- **folder_index_service.py:608-645 (Fix A)** — new alias-field indexing has no re-index note / index-version bump; existing workspaces won't pick up the new fields silently.
