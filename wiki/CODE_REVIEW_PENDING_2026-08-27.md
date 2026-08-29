# Pending Code-Review Issues — consolidated ledger (2026-08-27)

**Purpose:** every open review finding across all rounds, in ONE place, waiting for a
joint walkthrough. Items are open unless explicitly listed in a "Resolved" section below.
Companion files: `wiki/CODE_REVIEW_2026-08-27.md` (parallel reviewer's full report),
`SNAPSHOT_CHANGELOG.md`, task list (`TaskList` ids below).

**Sources merged:** (a) `/code-review` agent on v3.3.170 (`7f335c4`); (b) multi-team
adversarial workflow (`review:{canonical,samples,tests,gates,cross,snapshots}` +
refuter verification) on the same release; (c) parallel reviewer's report already at
`wiki/CODE_REVIEW_2026-08-27.md`; (d) older carried-forward rounds (tasks #345/#347/#349).

---

## 1 · v3.3.170 release review — confirmed (adversarially verified)

| ID | Where | Issue | Status |
|----|-------|-------|--------|
| **V1** | `backend/tests/jaccard_canonical.py:1593,1603,1628,1637` | TOP7→TOP11 re-pin touched only CANONICAL_EDGES (E5D4:1113, RDE3:1139). Four node-side notes/comments still say TOP7 — which on the fixed sample is the OPS_MBS ALTER@172, not the rrcdm INSERT@179-190. File contradicts itself. Verifier-confirmed. | Task **#371** |
| **V2** | `jaccard_canonical.py:1076` + `test_jaccard_benchmark.py:223-226` | Frequency-vote evidence "8× lowercase vs 1 uppercase" is arithmetically stale: repaired EAST5 has 11 lowercase (INSERT@41 + 10 ALTERs@166-175). Vote outcome unchanged. | Task **#371** |
| **V3** | `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_Digitallending.md:23-42,55-57` | DL ledger still certifies "562 lines / 21,411 bytes … MATCH EXACTLY" (now 21,439) and cites L111 `NVL(km_gl.MXKMBH,…)` as active evidence — commented out @110-111/147/167/176 in the repair. Doc is declared independent truth → real consistency break. | Task **#372** |
| **V4** | `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO.md:46` | Still lists `PCBACCT_NO`; repaired PL writes `PCB_ACCT_NO`@22. Descriptive §1 only, no benchmark row depends on it. | Task **#372** |
| **V5** | `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md:5122-23` | M3a premises now false after repair: "line 141 has no AS a", "7 ALTERs", "8 lowercase vs 1 uppercase". | Task **#372** |
| **V6** | `backend/tests/test_l2_case_merge.py:147-157,196-201` | Docstrings misattribute mechanism: `dis_bank_id` is NOT phantom-fallback routed — model attributes it directly to east5 (`source_tables=['east5_stzfxxb']`, anchored L76 `b.org_no As dis_bank_id`; L77 nvl collapses into it). settrace: `write_field_target.get()` never fires on the new sample. | Task **#373** |
| **V7** | `test_l2_case_merge.py:171` | `CHARGE_DEPARTMENT not in kids` passes only by CASE ACCIDENT: lowercase `charge_department` (PARTITION-clause twin @41 + ALTERs) IS on the east5 keeper. Breaks if labels ever case-fold like physical tables. | Task **#373** |
| **V8** | `test_l2_case_merge.py:12-19` (module docstring) | Still advertises T2 phantom-alias routing coverage that no assertion exercises anymore. | Task **#373** |
| **V9** | Coverage gap (design decision needed) | No assertion pins #289 fallback *behavior*. Refuter showed code DELETION is caught by DL/RFN byte-snapshots, but a silent behavioral regression in `l2_builder.py:684-690,758-763` ships green. Options: synthetic single-statement fixture exercising the fallback, or accept snapshot-only protection. | Task **#373** — await your call |
| **V10** | `SNAPSHOT_CHANGELOG.md` | Three snapshots rebaselined (DL 444n/659e, PL 303n/317e, EAST5 129n/164e) with no changelog entry — violates the file's own post-v3.3.164 rule ("every repin recorded with reason"). Rationale currently lives only in a jaccard_canonical comment. | Task **#374** |
| **V11** | `samples/sql_sample_v1/EAST5_STZFXXB_M.sql:59-63` | Rewritten regex class `"[~!@#$%&{}><+/=?、《》\[\]]"` is an uncorroborated replacement guess; possibly escaped at string-literal layer instead of regex layer (Hive/ODPS unescaping → `\[` terminates the class early → sanitizer no-ops for single special chars; sibling @58 uses unescaped RLIKE). Needs live ODPS parse check / screenshot evidence. Markers stripped without resolution record → repo now holds two standards (RFN keeps 21 markers). **ADJUDICATED #375 (2026-08-28, offline evidence round): verdict (c) engine-ambiguous; reconstruction-infidelity CONFIRMED; sample deliberately NOT edited (never-guess rule — true member set is pixel-illegible). Full truth table + ODPS decision list in §V11 notes below.** | Task **#375** — adjudicated, awaiting ODPS live check |
| **V12** | Provenance/process (no repo defect per se) | Commit body framed PL/DL as "annotation cleanup" but PL/DL had zero annotations at HEAD~1 — PL was a ~92-line identifier reconstruction (well-corroborated against DL/SUP/RFN). Record so future audits know provenance semantics. Pure literals ('A17200','TR08','02029902','F','I') remain SME-sign-off items. | discuss |
| **V13** | `l2_builder.py:1850` + `DataFlowApp.jsx:238,667` | **Merged-view seed orphan (user-reported "still orphans" on east5_stzfxxb.p_dt).** Engine data is clean (resolution 100%, zero parentless nodes in served payloads — verified against BOTH live prod workspaces). Root cause: default view after a matched search is `flow-merged`; `build_line_merged_edges` promotes field endpoints to parent tables so ALL 4 seed edges collapse into table-level FLOW edges (@41 folds with the write leg, @189 with the chain, @190 → self-loop), while R32's "node set never touched" keeps p_dt in `flow_node_ids` → renders with ZERO visible edges = floating orphan. Any closure where every field edge shares its line with a stronger rep shows it. Fix options: (A) frontend hide/badge fields in merged views; (B) drop promoted-away field ids from flow_node_ids; (C) guarantee the search seed ≥1 merged edge. Recommendation B+C. **RESOLVED (approach A — display-layer only; code is on HEAD but UNRELEASED, ships with v3.3.181 — already-shipped v3.3.180/R38 does NOT contain it):** `DataFlowGraph` passes `mergedView` (true for flow-merged/full-merged only) into the hook and `applyFlowVisibility`, which after the normal show/hide hides any `data.type === "field"` chip with zero visible incident edges inside one `cy.batch` — `.hide()`/`.hide()` class-free, never a position/layout change; tables/CTEs/aliases always stay; detailed views pass `false` and are untouched; no backend payload or benchmark-served closure/edge set changed (vitest 226 passed / build green). Residual: the seed's membership context stays readable through its owning TABLE box, which IS shown and connected (its merged FLOW edges). | Task **#376** — Resolved (display-layer; ships v3.3.181) |

### V11 notes · regex-escaping adjudication (#375, 2026-08-28 — offline evidence round)

**Question:** what does the reconstructed literal `"[~!@#$%&{}><+/=?、《》\[\]]"` @EAST5:59-63
actually compile to, and was the reconstruction right?

**1 · Semantics (sqlglot 30.12.0 in dev container + Python re, Java-class-equivalent).**
- sqlglot `mysql` (the project's parse dialect) **strips the escapes**: the pattern
  Literal for the current escaped form is byte-identical to the unescaped pixel-original
  form `[~!@#$%&{}><+/=?、《》[]]` — i.e. the repair is
  **semantically inert at project-parse level** (extraction/highlight see the same string
  either way, so no snapshot can distinguish them; none needed changing).
- sqlglot `hive` **retains** `\[\]` in the parsed Literal; sqlglot 30.12.0 has **no `odps`
  dialect** — engine truth is not derivable from sqlglot.
- Compiled-class truth table (inputs × both forms, replacement char `*`):

| input | ESCAPED `[~!@#$%&{}><+/=?、《》\[\]]` | STRIPPED `[~!@#$%&{}><+/=?、《》[]]` |
|-------|--------------------------------------|--------------------------------------|
| `a*b` | `a*b` (`*` not a member — unchanged) | `a*b` (unchanged) |
| `a]b` | `a*b` | **`a]b` — NO-OP** |
| `a、b` | `a*b` | **`a、b` — NO-OP** |
| `a@b` | `a*b` | **`a@b` — NO-OP** |
| `a[b` | `a*b` | **`a[b` — NO-OP** |
| `a@]b` | `a**b` | `a*b` (pair consumed, one `*`) |

  The STRIPPED form compiles to *one char from the class, followed by a literal `]`*
  (class closes at the first unescaped `]`; the trailing `]` becomes a sequence literal)
  → the hypothesized "sanitizer no-ops for single special chars" is **real, but only
  under the early-unescaping regime AND with the trailing `]` present**.

**2 · Cross-evidence (three independent reads of the original pixels, convergent).**
- Pre-repair git text (8909157, tesseract round): `"[~!@#$%&{}><+++/??=+?/、《》[]/I....]"`
  — **no backslashes** (marked OCR-UNCERTAIN, heavily garbled).
- Team 4 max-zoom read (V15) and the #375 4× re-read of `screenshots/case1-1.png`:
  original class is **single-quoted**, has **NO backslash anywhere** (explicitly none
  before any `[` `]` `~` `^` pipe), replacement is a **space `' '` not `'*'`**, and the
  member set differs from the reconstruction (includes `^`, quote chars, `￥`, `【】`,
  pipe; illegible runs `??`, `....` remain in BOTH reads).
- New signal: the original's wrapper `replace` calls (visible on the same pixels,
  collapsed by the repair) use `\r` / `\n` escapes — the author's own code relies on
  string-layer escape processing, which argues AGAINST the "backslashes survive into
  the regex" regime.
- Conclusion: the v3.3.170 reconstruction **added** `\[\]`, switched quote style,
  changed the replacement char, and normalized the member set — uncorroborated
  idealization confirmed (V11's original suspicion + V15).

**3 · Sibling corroboration: none available.** The only other regex literal in the
production samples is the sibling `RLIKE('[A-Za-z0-9]')` @58 — no escapable members,
uninformative. Zero backslashes in any other production sample string. No repo
convention exists to appeal to.

**4 · Why NOT edited (branch (ii) of the #375 decision rule).** Engine-level truth is
regime-dependent and not determinable offline: strip-regime (MySQL-like) → current form
≡ pixel-original (both degrade to the pair-matcher); preserve-regime → current form is
strictly better than the pixels; strict-C-lexer regime → the current form would not even
parse on ODPS. And the *correct* text is NOT recoverable: both zoom reads carry `[?]`
runs on the member set (even whether the first char after `[` is a negating `^` is
unsettled), so any rewrite is a fresh guess — barred by the standing never-guess rule.
No sample/snapshot/changelog/ground-truth change; no gates run (no file changed).

**5 · The ODPS live check must decide (run when available):**
1. `SELECT regexp_replace('a]b、c', '[~!@#$%&{}><+/=?、《》\[\]]', '*')` →
   `a*b*c` = preserve-regime (current text semantically correct; only quote/replacement
   fidelity per V15 remains); unchanged-or-pair-only = strip-regime (`\[\]` is dead
   weight); parse error = strict-lexer regime (the `\[\]` is a hard defect to remove).
2. Same input with the unescaped `[~!@#$%&{}><+/=?、《》[]]` form to pin the
   pixel-original's true behavior.
3. `SELECT '\['` and `SELECT '\r'` — strip/keep/error on unrecognized escapes.
4. Higher-DPI screenshot (or SME) for the member set, incl. the leading-`^` negation
   question, single quotes, and space replacement — then one combined EAST5 repair wave
   with benchmark-seed re-pin discipline (V15).

### V16 notes · R43 partition-DDL frames dropped from the L2 graph (task #384, 2026-08-28)

User ruling: "ALTER TABLE ADD PARTITION statements should not appear in the L2 graph — they are
folder names, not dataflow." Implemented display-layer only (`_drop_partition_ddl_frames` in
`l2_builder.py`, applied after the graph-cache load, before the flow filter). Reviewer-relevant
consequences:

- **EAST5 full-L2 counts moved**: 129→119 nodes / 168→148 edges (ten `output` VTs @L166–175 +
  their 20 edges). Flow closures unchanged (`east5_stzfxxb.p_dt` still 5n/7e). `test_l2_snapshot.py`
  (l2_snapshot_02 pins the pre-R43 counts) is EXPECTED TO FAIL — do not "fix" by reverting R43; the
  orchestrator regenerates all snapshots once the parallel team's work lands.
- **No cache-format bump, deliberately**: the graph cache keeps extraction truth (it still contains
  the frames), and the display projects them away on EVERY consumption path — probe-verified that a
  pre-R43 cache serves the identical post-R43 display. `GRAPH_CACHE_PREFIX` stays `graph_3_2_24`;
  `EXTRACTOR_VERSION` untouched (TOPn pins incl. TOP11 stay valid; jaccard 22/22 with invariants).
- **INV-1's DDL carve-out is moot** (R39.4 superseded): the frames are gone from the graph, not
  merely excluded from a closure; `test_inv1` keeps the two-sided assert as the R43 regression
  guard.
- Detection is conservative by design (statement text must open `ALTER TABLE` AND carry
  ADD/DROP/MSCK … PARTITION): column DDL, CREATE/CTAS, SET are out of scope pending evidence.

### Resolutions (2026-08-27 evening wave — ship in v3.3.181)

- **V1/V2 RESOLVED** (#371): all node-side TOP7 refs → TOP11 + a third `8×`-glyph vote comment found and synced; NORMALIZE_MAP note updated; consumer-grep proved no assertion depends on changed strings; benchmark 20/20 @ 1.0000 (`6343bfd`).
- **V6/V7/V8 RESOLVED** (#373, `af85d7a`): T2 docstrings rewritten to probed truth (direct attribution; probe table in report); case guard replaced with exact-spelling ownership assertions on BOTH tables (lowercase `charge_department` exists on ep side too — caught); `dis_bank_id` twin pinned in bdm_kids.
- **V9 RESOLVED** (#373, `af85d7a`): synthetic fixture `INSERT INTO dwd_pay_detail SELECT z.phantom_col AS carried_amt, r.keep_col AS kept_amt FROM real_src r` — asserts fallback routes `carried_amt` to the write target, with a no-INSERT contrast probe proving it is genuinely the fallback (mutation-proofed). 6/6 passed.
- **V13 RESOLVED** (#376, `72665e4`): display-layer — merged views hide edgeless field chips (`mergedView` flag through applyFlowVisibility/fitAllElements; detailed modes untouched; zero backend payload change). vitest 226+6 green at commit time. Residual: seed context remains via its connected owning TABLE box.
- **NEW V14 (report-only)**: direct `_classify_compound_nodes(...)` calls on JOIN-heavy scripts raise `TypeError: unhashable type: 'dict'` in `keeper_by_entity[_fold_physical(ekey)]` when an entity key is neither str nor tuple — `_build_l2_graph` does not hit it. Found by Team 2's probe harness.
- **NEW V15 (sample-content corrections, EXECUTABLE — evidence found locally)**: Team 4 proved the OCR screenshots survived in-repo (`screenshots/case1-*.png`, `case2-*.png`) and read them at max zoom: RFN L769 committed as `'G19'` but source reads `'S70'` (real mis-repair, non-seed sample); RFN L818/770 "dangling AND" is a phantom (the AND is inside a trailing comment); RFN L320 `LOAN_GRADE` is a DECODE expression, not `NULL`; EAST5 @59-63 original regex is single-quoted `[\~!@#$%^&{}><''""/?? =+￥/、《》【】/|....]` with replacement **space** (not `'*'`), no `\[`/`\]`, ~10 wrapper lines collapsed to 9 — V11's "uncorroborated guess" confirmed. Marker→band map in Team 4 report. Repair wave pending: EAST5 changes touch a benchmark seed → re-pin discipline required.

### Adjudicated — do NOT re-litigate

- **REFUTED:** "RE-PIN comment names the wrong dropped ALTER (OPS_CDT)". Direct probe of
  HEAD~1 contexts: `TOP1=166(OPS_CDT) … TOP6=174(GTRF_RFN)`, rrcdm=TOP7,
  **WPB_CDT_Digitallending@175 absent** from old parse. Comment in jaccard_canonical is CORRECT.
- **Clean bill (verified):** TOP11 arithmetic ✓ · all 12 benchmark cases 1.0/1.0 via true
  set-equality ✓ · snapshots byte-identical to live engine output ✓ · every rebaseline hunk
  traced 1:1 to sample diffs ✓ · gates 135 passed ✓ · CR10 RUE2/RDE2 notice inherited from
  v3.3.166, not grown ✓ · PL identifier repairs corroborated, not semantic drift ✓.
- **Design observations (lower priority):** RUE3 carries no `stmt` key so the J12-17
  endpoint check doesn't guard the upstream write leg (exposure class this release revealed);
  hand-enumerated 15+4 label lists in T2 tests vs closed-form invariant; TOPn pins derivable
  from anchor lines (all 7 pinned rows: output-VT line_start == row anchor) — brittleness note only.

---

## 2 · Parallel reviewer's findings (`wiki/CODE_REVIEW_2026-08-27.md`) — still open

Full detail in that file. Condensed register:

**HIGH**
- **H-S2** — hardcoded weak admin default `123456` (`config.py:42`). Fix: env secret / first-login change.
- **H-D1** — traceability rows still "awaiting GO" / ⏸ markers contradict ✅ requirement rows.
- **H-D2** — OCR harness tempdir leak (`harness.py:422` mkdtemp never removed).

**MEDIUM**
- **M-T1** — TVF alias `line_start` always 0 → same-label TVF aliases collapse across statements
  (`variable_extractor_v2.py:2121`, strict `_match_token_run` can't skip `'$(load_date)'` tokens).
- **M-T2** — schema-qualified TVF loses schema (`myschema.fn` registered as bare `fn`, collisions).
- **M-H1/M-H2/M-H3/M-H4/M-H5** — OCR harness: naive `;` split + global `declared` set;
  table names pollute `declared`; char-count min_h drops short glyphs (spurious flags);
  gutter-detect crops real code / empty-crop crash; batch aborts on first bad image.
- **M-E1** — merged vs detailed L2 share one layout-persistence key (`DataFlowApp.jsx:930`).
- **M-A1** — auth backoff caps per-key value but not key count (`auth_service.py:256-271`).
- **M-D1** — version drift worse: committed index.html meta = 3.3.166 (4 behind); RELEASE.txt
  VERSION=3.3.170 vs COMMIT=32a8e6a (v3.3.169) — NOTE: target_deploy.sh accepts ancestors by
  design; decide if manifest should name the release commit instead.
- **M-D2** — USER_IDENTITY / DATAFLOW_FORMAL_DEFINITION docs still describe removed notification entities.
- Carried: **M-C1** IDOR read endpoints · **M-C2** audit durability (/tmp) · **M-C3** zero-expiry sessions (accepted #279).

**LOW**
- **L-T1** topology_checker misses `function_table` connectivity; **L-T2** frontend styling parity deferred
  (acked by test marker); **L-T3** stale "15 types" docstrings (enum = 16); **L-T4** sql_model doc row omits view.
- **L-H1..H4** harness minors (PIL leak, dead margin, keywords masking undeclared-check, keyword votes).
- **L-S1** PL inline Chinese comments disagree with re-pinned aliases (OCR garbage in comments);
  **L-S2** 'A17200'/'02029902' unverifiable without DDL → SME; **L-S3** dis_bank_id double projection
  pre-existing vs docstring wording; **L-S4** same as V11 (one ODPS parse check).

---

## 3 · Older carried-forward rounds (tracked in tasks, details in those tasks)

- Task **#345** — remaining code findings: L-E3, L-E4, E11, M-F1, L-F1.
- Task **#347** — security + doc-staleness sweep leftovers (H-S1, H-D1 overlap §2, M-D1..D3, L-D1..D3).
- Task **#349** — deferred review items: L-E3, L-E4, L-BM4.
- Task **#370** — RFN OCR-repaired sample lost at revert (21 annotations remain) — bundle with V11/V12 evidence round.

---

## Resolved during the 2026-08-27/28 sessions (do not re-flag)

- **Release-pipeline stale-bundle race** (new defect class found by the hover trial):
  the image serves prebuilt `backend/app/static/`; v3.3.171–173 shipped v3.3.170's
  UI while /api/health reported new versions, and v3.3.177's stage-0.5 build
  predated the recovery commit (history looked inclusive, artifact wasn't). Fixed:
  release.sh stage 0.5 (rebuild + VERSION stamp + dist→static sync), and
  v3.3.178 redeployed with local-vs-deployed sha256 parity (`b8fa4496…`) plus a
  live functional check. → requirement R36 in the traceability matrix.
- **Edge-hover no-op** (user-verified, v3.3.176) and **edge chips** (v3.3.177),
  **minZoom 0.28 floor** (v3.3.175), **fit margins** (V-adjacent, v3.3.172/177):
  shipped and screen-verified (`hover_shots/FINAL_proof_v2.png`).
- Docs repaired with evidence this session (closes the doc halves of #372/#374):
  SNAPSHOT_CHANGELOG v3.3.170 entry; DL ledger re-reconciliation addendum
  (21,439 B; L110-111/147/167/176 now comments); PL doc PCBACCT_NO→PCB_ACCT_NO;
  BUG_ANALYSIS M3a premises updated (alias `a` declared @141; 11 lowercase / 10
  ALTERs). Code-side items in #371/#373 remain OPEN.
- **Loop-line redline detachment** (user-reported "a red line separately on the
  screen"): the merged-view filter loop-line's anchors parked at `sp.x - off` — a
  floating bar with no visual tie to the table. Fixed **v3.3.187**: anchored to the
  table's LEFT border (`box.x1 - gap`, vertical span clamped to the box,
  model-space anchor — never drifts on pan/zoom); **v3.3.190** ruling B1 clamps
  the gap to ~2px so the bracket visibly touches. Caption font zoom-compensated
  in the same v3.3.190 (floors ~11px on-screen). → R40.1/R40.2.
- **Story edges invisible (f648)**: the Field Story Filtered step's only edge
  renders ~0px (detailed: field→own-table endpoints coincide; merged: the
  self-loop is ~7px). Fixed **v3.3.189**: the step lights the synthetic chrome
  (`capL_<edgeId>` loop-line + `cap_<edgeId>` caption), under the guard rule
  story-active can only GROW the loop-line (width 9); the caption golds. → R40.5.
- **Cache headers** (the browser-side half of the recurring "deployed but user
  sees old UI" reports, stacked on the R36 static-sync race): with no Cache-Control,
  browsers applied RFC 7234 heuristic freshness to index.html and kept serving a
  whole OLD bundle. Fixed **v3.3.190** (`_VersionedStatic`, `backend/app/main.py`):
  index/non-asset paths `no-cache` (ETag still 304s), content-hashed
  `assets/*` `public, max-age=31536000, immutable`. → R40.6.
- Shipped in the same wave (not defects): Field Story step-through bar **v3.3.188**
  (R40.3), flow-reason panel REMOVED + bar relocated below the SQL panel
  **v3.3.189** (R40.4), history slim **v3.3.190+** (R40.7 — repo 1.21GiB → ~150MB
  clone; every existing clone must RE-CLONE).

---

## 4 · 2026-08-27/28 L2 readability wave — RESOLVED 2026-08-28 (details in §5)

- **Same-table edge (R40.8): RESOLVED** — the curve is real now (`control-point-step-size`
  via data-driven `loopstep`; the v3.3.185 `segment-points` styling never rendered — not a
  cytoscape 3.34 property), and clicking it highlights its SQL line (DOM-verified).
- **Fit / zoom floor (R41): RESOLVED** — `minZoom` 0.28 → 0.08 + `min-zoomed-font-size` 6
  (labels hide below legibility — boxes-only overview, user ruling) + user-initiated Fit
  passes `recenter:false` (no post-Fit seed re-center). Audit: fit wanted 0.08–0.09 vs the
  0.28 floor (87/129 nodes hidden); floor-lift probe 129/129 visible.
- **Task #380 (multi-user matrix): RULING CLOSED** — POST scan/index are creator-only
  (participants get 403, same rule as #272) + regression test.
- **#370 (RFN OCR): COMPLETE** — 21 markers → 0 across the 13 case2 screenshot pages; all
  four samples now clean (§5). **#375 (V11 ODPS live check) remains OPEN** — external
  evidence still required.

---

## 5 · 2026-08-28 resolution wave — audits #383/#386, RFN #370, legacy sweep (pending v3.3.191+ release)

All items below are landed in the working tree, staged for the next release. Do not re-flag.

### Fixed this wave

- **R40.8 self-loop curve** — see §4. The Filtered story step grows the curve under the
  existing width-9 guard (R40.5); the dead `segp`/segments bracket machinery was removed.
- **R41 fit/zoom** — see §4 (amends R35.2 / decision #24: legibility moved off the zoom
  clamp onto the font gate).
- **#380 creator-gating** — POST scan/index creator-only (403 participants) +
  `test_scan_and_index_non_creator_rejected_with_403`.
- **F2 (audit #383) — CTE index gap:** CTE `table_index` entries received fields but never
  the defining script, so the search intersection was empty (TEMP_RFN / temp_kmbh_*
  unsearchable). Invariant installed at 3 attribution sites in `folder_index_service.py`
  (fields recorded from a script imply the script in `table_index[t]["scripts"]`);
  unqualified-only CTE ruling preserved; +6 tests (`test_folder_index_cte.py`), 128
  regressions green. → R2.9.
- **F5 (audit #383) — casing UX:** case-insensitive name resolution against the index
  (`resolveNameCi` in `utils/nameFilter.js`) with canonical echo + inline "no such
  table.field in the index" message replacing the silent no-op; +10 tests. → R2.10.
- **Table-duplication audit (#386) — ONE real bug:** MERGE targets did not join the
  physical fold in `l2_builder` (a table MERGE-INTO'd in one statement and read/written in
  another rendered as two compound nodes). Fixed (2 conditions; aliases excluded) + 3 T3
  regression tests (`test_t3_merge_target_folds_into_physical_keeper`,
  `test_t3_read_first_order_folds_too`, `test_t3_one_char_apart_tables_stay_distinct`).
  Adversarial cases prove schema/backtick/case twins were already folded and
  1-char-apart tables never over-merge. → R5.12.
- **#370 RFN OCR recovery COMPLETE:** 21 markers → 0 across the 13 case2 screenshot pages,
  pixel-topology-glyph evidence; two bonus finds (restored the missing rrcdm INSERT header
  @L1396); gates green (parse_errors 0, jaccard 1.0000, snapshot 02 regenerated with a
  1:1-audited delta + `SNAPSHOT_CHANGELOG.md` entry). ALL FOUR samples now carry zero
  OCR-UNCERTAIN markers.
- **R40.10 Field Story Joined/Transformed stage** (not a review finding, shipped in the
  same wave): 6th stage (user-authorized ≤10) for JOIN/TRANSFORM/COMPUTED/WINDOW/AGGREGATE
  edges, ordered between Read and Filtered; random-10 audit evidence (49 unclassified
  narrative edges, +30 projected steps across 7/10 fields); tests extended.

### #386 rulings (filed — do not re-litigate)

1. **CTE-shadows-physical semantics:** the physical fold never swallows a CTE context node
   that shadows a physical table name — CTEs stay per-context by design.
2. **RFN sample typo pairs:** `temp_dqrg`/`dqrq` and `TEMP_BDM_…_01` vs `_1`/`_02` are
   REAL distinct tables in the source (sample truth preserved verbatim) — never
   over-merge candidates. Confirmed again 2026-08-29 against the repaired sample:
   `temp_dqrq_normal_01`/`_02` (@150/@175, joined @794) and `TEMP_BDM_ACC_LOAN_INFO_01`
   (@290, read @765) stay as authored — KEPT.
3. **RFN duplicated INSERT block (L866/L1167):** deliberate duplication in the sample
   (a deliberate backfill re-run), not an extractor or fold defect — KEPT.
4. **Alias-label collisions:** informational only — no action.
5. **CTE scope (2026-08-28.4) — a CTE's name is visible only inside its own statement.**
   A LATER statement's bare reference to a CTE's name registers a PHYSICAL table read
   (`_is_cte_name`, statement-scoped visibility); in-scope refs keep folding. Because the
   model still matches owners by the shared `name` string, `l2_builder` disambiguates at
   display time via `_stmt_root` + `field_owner_key` — the out-of-scope read's columns land
   on the physical compound, never on the `cte_table` node. → R5.13.
6. **K3's three RFN judgment-call repairs stand as-authenticated (NOTE #16,
   2026-08-29):** `:492` empty-literal RHS `= ''`, `:800-801` filter demoted to a
   trailing comment, `:903` invented `'2024-08-31'` guard — pixel-pass
   authenticated, flagged by red-team as truth-matters-if-wrong, baked into the
   rebaseline consciously. Full record: `wiki/CODE_REVIEW_2026-08-28.md` →
   "Adjudication record — the three K3 judgment-call repairs".

### Legacy sweep — §2/§3 ledger resolutions

- **H-D1 — SHIPPED v3.3.165 with evidence:** the traceability rows were flipped ⏸ → ✅
  against verified code (2026-08-28); they no longer contradict the requirement rows.
- **OCR harness backlog — ALL FIXED with live-run proof:** H-D2 (tempdir leak) +
  M-H1..M-H5 + L-H1..L-H4 (`tools/ocr/harness.py`).
- **L-T1 — FIXED:** `topology_checker` now covers `function_table` connectivity +
  test (`test_tvf_columns_covered_by_column_connectivity_check`).
- **L-T3/L-T4 — FIXED:** stale "15 types" docstrings + the sql_model doc row (view) —
  `models/sql_model.py`.
- **L-BM4 — residue cleared.**
- **Verified-fixed, no action:** L-D1..L-D3, M-D3, L-E11, M-F1, L-F1, H-S1, M-E1.
- **POSTPONED (documented, deliberate):** L-E3; **L-E4** (folds into R44's
  `EXTRACTOR_VERSION` bump — one cache invalidation, not two); **H-S2** (weak admin
  default accepted per the user's dev-phase ruling).

### Still open after this wave

*(2026-08-29: the first three bullets are the genuine remainder. The bullets after them record
items this ledger previously listed as open that the 2026-08-29 wave closed — kept inline, with
their verdicts and pointers, so nothing is silently dropped.)*

- **#375 / V11** — EAST5 regex escaping layer; needs the ODPS live check (external).
- **V12** — SME sign-off for pure literals ('A17200', 'TR08', '02029902', 'F', 'I').
- **§2 remainder:** M-T2 (schema-qualified TVF), L-T2 (frontend styling parity, acked),
  M-A1 (backoff key cardinality), M-C1/M-C2/M-C3 (carried security observations),
  L-S2/L-S3/L-S4 (sample/literal provenance).
- **R44 (walker occurrence coverage) — CLOSED 2026-08-29 (was IN FLIGHT): LANDED** as
  tasks #385–#387 + R45, `EXTRACTOR_VERSION 2026-08-28.3 → 2026-08-28.7` (write-side /
  derived-read / GROUP-BY / occurrence-line twins, OVER-line WINDOW anchors, l2_builder
  write-target parenting; .5 adds LITERAL write twins + the bare-INSERT set-op merge; .7 is
  K4's paren-balance diagnostics bump folding L-E4's cache invalidation). → R44.1 ✅ in
  `REQUIREMENTS_TRACEABILITY.md`. Still open under it: the benchmark re-pin (R44.2) and the
  unified snapshot regeneration (R44.3).
- **2026-08-28 code review (`wiki/CODE_REVIEW_2026-08-28.md`) — CLOSED 2026-08-29:** all 31
  first-pass findings adjudicated (23 fixed, 6 false positives with pixel/OCR or code-gating
  evidence, 2 evidence-based deferrals). Per-finding verdict table in that file's
  §"Resolution status (2026-08-29)". Nothing from that review needs a ledger entry here.
- **User-scenario simulation (2026-08-29, 50 seeded targets, 4 teams) — its fixes are landed
  or tracked as requirement rows, not ledger items:** backend case-insensitive search (R2.11 ✅),
  sample repairs RFN +2 parens / PL stray `;` @L19 (R13.7 ✅, jaccard re-pin pending), family-3
  occurrence twins (R44.1 ✅), chip-decoration guard + banner/autocomplete UX + zero-line click
  feedback + Fit re-verified in the real UI (R40.11 ✅); still in flight: field-chip
  `line_start` + banner text + direction default flip (R37.6, F-B1) and filter-operand twin
  edges (R44.4, F-E1). Headline: click → SQL-highlight is EXACT (30/30 browser PASS; 0
  parser-span violations across 16,129 edges / 7,745 nodes).
- **Snapshot note:** ALL L2 snapshots regenerate together at the next release (R43 DDL-drop +
  RFN #370 + the R44 twins + the F-B1 chip `line_start` keys + the K3 sample repairs). The red
  set is expected to grow ≈46 → ~75 before that wave runs — see the DRAFT/PENDING entry at the
  top of `SNAPSHOT_CHANGELOG.md`. Snapshot failures before then are expected rebaselines, NOT
  regressions.

---

## Suggested walkthrough order (when you have time)

*(Refreshed 2026-08-29 — items resolved by the §5 wave, the R44 landing, the 2026-08-28 review
adjudication and the simulation fixes are dropped; see §5 + the "Resolved" sections above.)*

1. **Needs external evidence:** #375/V11 (ODPS live check for the EAST5 regex layer) and
   V12 (SME sign-off for the pure literals) — the only V-items still open.
2. **Security triage (§2 remainder):** M-C1, M-C2, M-A1; H-S2 is POSTPONED by the user's
   dev-phase ruling (§5).
3. **Extractor correctness:** M-T2 (schema-qualified TVF) — will need snapshot rebaseline
   if fixed.
4. **Odds and ends:** L-T2 (frontend styling parity, acked), L-S2/L-S3/L-S4.
5. **R44 sign-off:** the walker landed (R44.1 ✅) — verify against the RE-DERIVED benchmark
   (R44.2, in flight) once the unified snapshot regen (R44.3) ships.

## #399 L1 compounding side effect (2026-08-29, F-G — logged for review)
Alias-target searches that previously stamped `flow_empty` → `match_mode: "no_flow"` (Decision-2's dead end) now return `match_mode: "exact"` with a real L1 graph, because `l1_builder.py:322` drives the L1 field-flow projection from the same W1 walker F-G extended (4 of 12 S1 alias targets flipped: SSALSFP, P1×2, dsf_tm, stzf). Script sets unchanged (index-driven). Partially delivers #400 for free; L1-visible behavior beyond #399's L2 scope — flagged for the user walkthrough.
