# Pending Code-Review Issues — consolidated ledger (2026-08-27)

**Purpose:** every open review finding across all rounds, in ONE place, waiting for a
joint walkthrough. Nothing here has been fixed yet (source untouched per standing rule).
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
| **V11** | `samples/sql_sample_v1/EAST5_STZFXXB_M.sql:59-63` | Rewritten regex class `"[~!@#$%&{}><+/=?、《》\[\]]"` is an uncorroborated replacement guess; possibly escaped at string-literal layer instead of regex layer (Hive/ODPS unescaping → `\[` terminates the class early → sanitizer no-ops for single special chars; sibling @58 uses unescaped RLIKE). Needs live ODPS parse check / screenshot evidence. Markers stripped without resolution record → repo now holds two standards (RFN keeps 21 markers). | Task **#375** |
| **V12** | Provenance/process (no repo defect per se) | Commit body framed PL/DL as "annotation cleanup" but PL/DL had zero annotations at HEAD~1 — PL was a ~92-line identifier reconstruction (well-corroborated against DL/SUP/RFN). Record so future audits know provenance semantics. Pure literals ('A17200','TR08','02029902','F','I') remain SME-sign-off items. | discuss |
| **V13** | `l2_builder.py:1850` + `DataFlowApp.jsx:238,667` | **Merged-view seed orphan (user-reported "still orphans" on east5_stzfxxb.p_dt).** Engine data is clean (resolution 100%, zero parentless nodes in served payloads — verified against BOTH live prod workspaces). Root cause: default view after a matched search is `flow-merged`; `build_line_merged_edges` promotes field endpoints to parent tables so ALL 4 seed edges collapse into table-level FLOW edges (@41 folds with the write leg, @189 with the chain, @190 → self-loop), while R32's "node set never touched" keeps p_dt in `flow_node_ids` → renders with ZERO visible edges = floating orphan. Any closure where every field edge shares its line with a stronger rep shows it. Fix options: (A) frontend hide/badge fields in merged views; (B) drop promoted-away field ids from flow_node_ids; (C) guarantee the search seed ≥1 merged edge. Recommendation B+C. | Task **#376** — await approach ruling |

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

## Resolved during the 2026-08-27 session (do not re-flag)

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

---

## Suggested walkthrough order (when you have time)

1. **Quick doc repairs, no decisions needed:** V1+V2 (#371), V3-V5 (#372), V10 (#374) — could be one batch commit.
2. **Needs your ruling:** V6-V9 (#373): fix docstrings now + decide whether to add a synthetic
   fallback-behavior test or accept snapshot-only protection.
3. **Needs external evidence:** V11/V12 (#375, #370) — screenshots/DDDL/SME sign-off.
4. **Security triage:** H-S2, M-C1, M-C2, M-A1 (§2).
5. **Extractor correctness:** M-T1, M-T2 (§2) — will need snapshot rebaseline if fixed.
6. **Odds and ends:** harness M-H*/L-H*, frontend M-E1/L-T2, doc H-D1/M-D2/L-T3/L-T4/S1.
