# Code Review — 2026-08-27 (v3.3.169 → v3.3.170)

**Reviewer:** code-review agent + 3 parallel sub-agents (TVF feature / OCR harness / sample-ground-truth slices).
**Scope:** `VERSION=3.3.170`; commits since the last round — `9b935ca` (v3.3.169 TVF row-source modeling),
`d4671e7` (restore OCR harness), `32a8e6a` (v3.3.169 release), `7f335c4` (v3.3.170 sample repair + snapshot rebaseline).
**Method:** static review + sqlglot parse checks + targeted pytest runs (agents); no source modified.

---

## Verdict

The v3.3.170 sample repair is **sound**: the prior review's suspicion that `CAPTIAL_RATIO` / `OTHRE_PY_GUARWAY`
etc. were OCR typos was **wrong** — those are the system's canonical column names (verified against the
RFN/DL sibling samples that target the same table). v3.3.169's TVF-as-`FUNCTION_TABLE` feature works but has
one real Medium (TVF alias `line_start` always 0 → same-label aliases deduplicate across statements) and one
Low/Medium (schema-qualified TVF loses its schema). The OCR harness is committed with the two prior findings
still unfixed (tempdir leak, naive `;` split) plus several new robustness issues.

---

## HIGH (open)

### H-S2 — Hardcoded weak default admin credential (carried)
- `backend/app/config.py:42` `{"admin@hsbc.com": "123456"}`; the comment at `:37` explicitly says "keep unchanged".
  Still guessable on first attempt despite rate limiting.
- **Fix:** provision admin from an env secret with a strong/generated password, or force first-login change.

### H-D1 — `REQUIREMENTS_TRACEABILITY.md` code-review rows still "awaiting GO" (carried)
- `wiki/REQUIREMENTS_TRACEABILITY.md:303` section header "queued, awaiting GO"; `:328` "11 tasks … Awaiting GO";
  13 `⏸` marker lines still present. Same tasks are marked ✅ in the requirement rows → self-contradictory.
- **Fix:** flip the ⏸ rows to ✅ and reset the summary.

### H-D2 — OCR harness leaks a temp dir on every image (new, carried from prior harness review — still unfixed)
- `tools/ocr/harness.py:422` `tempfile.mkdtemp(prefix="ocr_")` never removed; no `shutil.rmtree`/`TemporaryDirectory`.
- **Fix:** wrap the body in `with tempfile.TemporaryDirectory(prefix="ocr_") as tmpdir:`.

---

## MEDIUM (open)

### M-T1 — TVF alias `line_start` always 0 → same-label TVF aliases collapse across statements (new, v3.3.169)
- `backend/app/extractor/variable_extractor_v2.py:2121` (TVF block `:2023-2040`). The alias var is registered with
  `def_site=([[name, alias]], node, context)`; `_match_token_run` (strict adjacency, only skips STRING/AS) cannot
  skip the function-call tokens `('$(load_date)')` between name and alias, so `line_start` stays 0.
- `l2_builder` alias dedup key `(alias_parent_id, label, alias_line)` then merges distinct instances
  (e.g. `v_js_purpose_code('…') p1` at two different lines; `v_bdm_customer_all('…') a` in exists6/exists7).
- The rebaselined snapshots lock this in (one `p1`/`a` alias node with `line_start:0` instead of per-context nodes).
- **Fix:** register the TVF alias with a loose/`ret_last` def-site run, or a run of `[alias]`, so it resolves its real line.

### M-T2 — Schema-qualified TVF loses its schema (new, v3.3.169)
- `backend/app/extractor/variable_extractor_v2.py:2034` — `name = _clean(fn_name)` drops `table.db` for
  `myschema.fn('x') f`; registered as bare `fn` → same-named functions in different schemas collide.
- **Fix:** build `name` from the qualified form (`f"{_clean(table.db)}.{fn_name}"`) when `table.db` is set.

### M-H1 — `validate_sql` still splits on `;` + one global `declared` set (carried — still unfixed)
- `tools/ocr/harness.py:354-387`. Cross-statement false-negatives; `sql_text.split(";")` also breaks on semicolons
  inside string literals/comments.
- **Fix:** parse with sqlglot and evaluate qualifiers per-statement scope.

### M-H2 — `declared` registers physical table names, not just aliases (new)
- `tools/ocr/harness.py:368-372` adds `t.name` in addition to alias → any qualifier equal to a table name used
  elsewhere is never flagged, weakening the undeclared-qualifier check.
- **Fix:** only add the effective reference/alias (`t.alias_or_name`).

### M-H3 — char-count heuristic drops short glyphs → spurious `char-gap` flags (new)
- `tools/ocr/harness.py:116` `min_h=3` excludes periods/commas/underscores → `n_chars` undercounts, so `flag_band`
  (`:308-310`) emits false `char-gap-*` flags.
- **Fix:** lower `min_h` to 1 (or detect baseline-height text separately).

### M-H4 — `detect_gutter_left` can crop real code / produce empty crops (new)
- `tools/ocr/harness.py:166-172` — a 3-column whitespace gap after indentation triggers a false gutter; if the run
  ends at `w-1` it returns `w`, making `binv[y0:y1, x0:]` empty and cv2 raises.
- **Fix:** require a wider gap / verify the left block looks like a line-number gutter; clamp `x0 < w-1`.

### M-H5 — batch run aborts on first bad image (new)
- `tools/ocr/harness.py:465-466` `reports = [process_image(...) for p in args.images]` — one failure kills the run.
- **Fix:** loop with per-image `try/except` and emit an error record.

### M-E1 — Merged vs detailed L2 views still share one layout-persistence key (carried)
- `frontend/src/DataFlowApp.jsx:930-931` — `savedPositions`/`onPositionsChange` use `resumeLayoutKey('l2', script)`
  for both merged and detailed pairs; a manual drag in one mode pins the table in the other.
- **Fix:** persist merged views under `l2:merged:{script}` or gate `savedPositions` off in one mode.

### M-A1 — Backoff fix incomplete: unbounded `_failed_users`/`_failed_ips` cardinality (carried)
- `backend/app/services/auth_service.py:256-271` — caps only per-key value, not the number of keys.
- **Fix:** bound total entries (LRU/TTL) or periodic sweep.

### M-D1 — Version drift (carried, now worse)
- `frontend/index.html:19` + `backend/app/static/index.html:19` meta = `3.3.166` (**4 releases behind** `3.3.170`).
- `CLAUDE.md:14` = `3.3.166`; `wiki/REQUIREMENTS_TRACEABILITY.md:1` = "V3.3.166".
- **New:** `docker_image/RELEASE.txt` reports `VERSION=3.3.170` but `COMMIT=32a8e6a` (the v3.3.169 release), not `7f335c4` — artifact provenance inconsistent with declared version.
- **Fix:** run deploy stamping so the committed bundle carries the right meta/commit; bump traceability/CLAUDE.

### M-D2 — Cross-doc still defines removed notification/visit entities (carried)
- `wiki/USER_IDENTITY_AND_WORKSPACE_EMAILS.md` and `wiki/DATAFLOW_FORMAL_DEFINITION.md` still describe
  notifications/`/api/notifications`/inbox/Open Visit (removed #322/#285).
- **Fix:** remove/annotate as already done in SOLUTION_DESIGN.md.

### Carried (still open from prior rounds)
- **M-C1 — IDOR** on workspace READ endpoints (`workspace.py`) and `logs.py` `stream_logs`.
- **M-C2 — Audit log durability** (`workspace_service.py:10` `/tmp/workspaces`).
- **M-C3 — Zero-expiry sessions** (accepted #279).

---

## LOW (open)

### TVF feature (v3.3.169)
- **L-T1 — topology_checker inconsistent table-type set:** `backend/app/services/topology_checker.py:163`
  `_check_column_connectivity` still uses `("table","view","cte","merge_target","subquery")`, missing
  `function_table` (unlike `:52` and `:200`). `fn.col` is silently skipped from connectivity checks.
- **L-T2 — frontend parity deferred:** new `variable_type:"function_table"` renders with the default grey fallback;
  `graphStyles.js`/`App.jsx` colors/shapes/filter not updated (acknowledged in `test_type_styling.py:29`
  `FRONTEND_DEFERRED`). Track the frontend task.
- **L-T3 — stale "15 types" docs:** `test_type_styling.py:1`, `test_node_types.py:1,443` still say "15 types"
  though the enum is now 16.
- **L-T4 — `sql_model.py:155` Data Source doc row omits `view`** (pre-existing) while adding `function_table`.

### OCR harness (d4671e7)
- **L-H1 — `load_bgr` fallback leaks PIL handle / unhelpful `ImportError`:** `tools/ocr/harness.py:56-58`.
- **L-H2 — `binarize` dead `max(12, …)` margin:** `:66-67` always 30.
- **L-H3 — `_SYSTEM_QUALIFIERS` includes keywords `values`/`lateral`/`mysql`:** `:340-341` masks real errors.
- **L-H4 — `identifier_votes` counts SQL keywords** (`SELECT`/`FROM`/`WHERE`): `:393-399`.

### Samples / ground truth (v3.3.170)
- **L-S1 — PL inline comments disagree with canonical semantics** (doc only): `BDM_ACC_LOAN_INFO_PL.sql:38,87,109,129,137,138,140,219`
  keep old/OCR Chinese comments while aliases were re-pinned to canonical names — align to RFN/DL comments
  (e.g. `IS_PRATTWHITNEY_LOAN --普惠电视惠农贷款标识` contains OCR garbage "电视").
- **L-S2 — `HUB_ITEM_CODE='A17200'` and `BUSINESS_TYPE='02029902'` not independently verifiable** (no target DDL in repo) → SME sign-off.
- **L-S3 — EAST5 `dis_bank_id` projected twice** (`EAST5_STZFXXB_M.sql:87-88`, pre-existing); `test_l2_case_merge.py`
  docstring describes it as a single phantom projection.
- **L-S4 — EAST5 regex class `[~!@#$%&{}><+/=?、《》\[\]]`** (`:59,61`) — escaping improved, but `\[` inside a
  double-quoted MaxCompute literal needs one live ODPS parse check.

---

## Corrected / verified this round

- **Prior Medium retracted — "typo aliases" were NOT typos.** `CAPTIAL_RATIO`, `OTHRE_PY_GUARWAY`, `PGUPER_AMT`,
  `LOAN_ORIGI_TYPE`, `LOAN_PURPOSE_SNI`, `PENALTYINT_AMT`, `COMPOUNDINT_AMT`, `INTEREST_BALANCE2`, `USEOFUNDS_TYPE`,
  `IS_GREENLOAN`, `IS_GREEN_TRANSFINA`, `IS_VTR_GTR`/`VTR_GTR_TYPE`, `IS_PRATTWHITNEY_LOAN`, `LOAN_EX_GU_NO`,
  `tag_gbgf`, `NOMINAL_ACC`, `SIGN_CHANNEL`, `PCB_ACCT_NO` all match the RFN/DL sibling samples verbatim — they are the
  system's canonical column names; the PL sample was previously using non-schema names and is now correctly re-pinned.
- **Verified sound:** `jaccard_canonical.py` TOP7→TOP11 re-pin (10 ALTERs now), `test_l2_case_merge.py` ownership
  assertions, snapshot field-label ↔ SQL-alias consistency, `LASTDAY` (correct MaxCompute fn) vs `LAST_DAY`.
- Both committed samples parse under sqlglot hive/spark (PL → 4 stmts, EAST5 → 13 stmts).

---

## Not reviewed

- Full test-suite execution (Python 3.14 sandbox hangs on TestClient); agents ran targeted suites only
  (`test_tvf_row_source`/`test_node_types`/`test_type_styling` → 72 passed; dependency/physical/snapshot/extractor/
  graph-integrity/walkable → 195 passed).
- Live ODPS/MaxCompute engine execution of the repaired samples.
