# Ground Truth — Seed `ods_hie_ipacmsp.iiapty` (downstream-only shape, R29)

> **Seed:** `ods_hie_ipacmsp.iiapty` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.2/§3.1/§4 REPAIRED 2026-08-12 with probe evidence (repin round: the row-level-continuation chain runs to the rrcdm write @211 — see §2.2/§3.1). **REPAIRED AGAIN 2026-09-01** (§2.2/§3.1/§4, USER RULING 2026-09-01 rule 7-A — "write leg only": the chain's rrcdm leg is RETIRED, because the job-log statement never writes the `iiapty` column; see §2.2)
>
> **CR10 re-derivation status (2026-08-13):** the §3.1 13-node / 17-edge closure was REPINNED FROM THE SERVED CLOSURE (the point-15 repin round, probe-pinned) — circular per the CR10 ruling. The independent re-derivation (backend/tests/test_independent_r29_ground_truth.py) re-verifies the closure against the SQL SOURCE TEXT: the seed zone (LEFT JOIN ods_hie_ipacmsp p5 @151, p5.iiapty = p4.iiapty @153), the sup write @160, the p2 self-join zone @199-203, and the rrcdm continuation (@211 insert / @223 FROM / @225 data_dt filter) are all SQL-verifiable; the exact edge FORMS flagged `pending` in jaccard_canonical.py (IID3/IID6/IID8 — engine-emission conventions) must be re-derived before they count as independent ground truth.
>
> **Shape purpose:** the queried field has READERS but NO WRITERS in the workspace (ODS source table) — exercises the **downstream join-key closure** case and the **EMPTY upstream projection**.

## 1. Workspace facts (verified 2026-08-12)

| Script | Site | Usage |
|--------|------|-------|
| BDM_ACC_LOAN_INFO_SUP_M.sql | 151–152 | `LEFT JOIN ods_hie_ipacmsp p5 ON p5.iiapty = p4.iiapty AND p5.p_dt = p4.p_dt` — the join key `p5.iiapty` is the seed instance |

- **Writers:** none — `ods_hie_ipacmsp` is an ODS source table; no script in the workspace writes it (grep verified: only the comment header @3 and the LEFT JOIN @151).
- The join @151 is inside the **sup-write statement** (the statement whose `INSERT OVERWRITE bdm_acc_loan_info_sup` is @160, `WHERE p1.data_dt = '$(load_date)'` @158).

## 2. L1 ground truth

### 2.1 Upstream L1 (writing — DEFAULT direction)

**EMPTY projection.** No script writes `ods_hie_ipacmsp` at all — there is no writing flow. L1 must render an empty directional flow as a clear "no writing flow" state (message, not an error).

### 2.2 Downstream L1 (reading)

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. **REPAIRED 2026-08-12 (repin round, probe evidence — row-level continuation):** the using statement's SELECT ROWS are selected BY the join key, so the effect rides the statement's output ROWS and flows into ALL its write targets — even though `iiapty` itself is not among `bdm_acc_loan_info_sup`'s written columns (the user's row-level ruling: "the selection of rows are from the queried field"). Chain: seed join usage @151-153 → sup write @160 (and the statement's self-CTE read `p2` @199). **REPAIRED AGAIN 2026-09-01 (USER RULING 2026-09-01, rule 7-A — "write leg only"):** the chain's former last leg — the rrcdm statement filters `sup.data_dt` @225 (a column the sup write produced) and writes `rrcdm_job_log_exec_par` @211 — is RETIRED. The 2026-08-12 row-level continuation is bounded by the write leg: a statement continues the searched field's flow into ITS OWN write targets only when the SEARCHED FIELD IS THE COLUMN BEING WRITTEN (`rrcdm_job_log_exec_par.data_dt` @211/@213 is written from the literal `'$(load_date)'`, and the `iiapty` column is not among the log's written columns), so the `sup.data_dt` FROM-read @223/@225 does not drag the statement's write leg in. Corollary: for fields the job-log does NOT write (`iiapty`, `lending_ref`, …) NOTHING of the log statement shows; for the fields it DOES write (`data_dt`) the write leg @211 IS served — see GROUND_TRUTH_RRCDM_JOB_LOG_EXEC_PAR.md and the `sup`/`bdm` `data_dt` cases of the Jaccard gate (rows 16/17/X3).

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `ods_hie_ipacmsp` (the read instance — the queried table), `bdm_acc_loan_info_sup` (the using statement's write target @160)
- **Excluded:** `rrcdm_job_log_exec_par` — the continuation write @211 is RETIRED (USER RULING 2026-09-01 rule 7-A, "write leg only": the log never writes the `iiapty` column, so the log statement contributes nothing to this closure). `bdm_acc_loan_info` — the statement's other join inputs (p4, rollover_loan_info, `bdm_sys_acc_loan_info`, …) and the other join key `p4.iiapty` (a different field instance) — they are not in the seed's instance flow.

## 3. L2 ground truth (per script)

### 3.1 Downstream L2 (SUP_M)

The seed `p5.iiapty` is a **JOIN-KEY usage** in the sup-write statement. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 13 nodes / 17 edges / 10 highlight lines):** the row-level continuation (user ruling) carries the effect through the sup write into the rrcdm statement. **REPAIRED AGAIN 2026-09-01 (USER RULING 2026-09-01 rule 7-A — "write leg only"): the served closure is 7 nodes / 9 edges / 5 highlight lines** — the rrcdm statement's legs (@211 write, @223 FROM read, @225 `sup.data_dt` filter) and the co-written sibling columns (`lending_ref`/`data_dt`/`charge_department` SCHEMA@201/@202/@203, the seed-zone JOIN@203) are OUT: the log writes none of them for this seed, and the R46c canonical re-derivation removed the trunk rows (class X4) with the J1 value-cone gate enforcing it. Served closure: the seed zone @151-153 (`iiapty` — the p5 join-key instance — `p5` alias of `ods_hie_ipacmsp`: ALIAS@151 / REF@151 / TABLE_FLOW@151 / JOIN@153 / SCHEMA@153) → the sup-write statement's output VT `⟐output` @64 (TABLE_FLOW@64) → its write leg into `bdm_acc_loan_info_sup` (TABLE_FLOW@160) with the statement's self-CTE source `p2` @199 (TABLE_FLOW@199, ALIAS@160). The join's OTHER keys (`p4.iiapty`, `p5.p_dt`, `p4.p_dt`) are different field instances. The Jaccard harness pins these as rows IID1-7/IID9/IID11 (jaccard_canonical.py points 15/24); highlight lines: 64/151/153/160/199.

### 3.2 Upstream L2

Empty for all scripts (no writers anywhere).

## 4. Edge cases pinned

- ODS source field with no writers → **empty upstream projection** (the first such case in the suite).
- JOIN-key usage counts as a USE (the effect scope includes WHERE, joins, and any usage — user ruling 2026-08-12).
- **Row-level continuation, bounded at the write leg (REPAIRED 2026-08-12, user ruling; RE-BOUNDED 2026-09-01, USER RULING 2026-09-01 rule 7-A — "write leg only"):** the statement that USES the queried field carries the effect into ALL its write targets — even when the seed is not among the written columns, because the SELECTED ROWS are the rows selected by the seed (join key @151 → sup write @160). The 2026-08-12 second hop (a later statement whose ROW-SELECTION uses a column the write produced continues the chain into ITS write targets) is SUPERSEDED: the continuation runs through the searched field's OWN write leg only. A statement whose write does not include the searched column (`rrcdm_job_log_exec_par` writes `data_dt` @211/@213, never `iiapty`) contributes NOTHING to the closure — its FROM-read of the searched table (@223) and its row-selection filter (@225) are not the searched field's flow. `data_dt`-class fields DO get that write leg (rows 16/17/X3 of the `sup`/`bdm` Jaccard cases); `iiapty`/`lending_ref`-class fields get nothing.
