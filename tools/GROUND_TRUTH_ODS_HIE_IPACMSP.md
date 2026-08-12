# Ground Truth — Seed `ods_hie_ipacmsp.iiapty` (downstream-only shape, R29)

> **Seed:** `ods_hie_ipacmsp.iiapty` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — ground truth built before coding; implementation pending
>
> **Shape purpose:** the queried field has READERS but NO WRITERS in the workspace (ODS source table) — exercises the **downstream-only** case and the **EMPTY upstream projection**.

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

The join usage @151 selects the rows of the sup-write statement → the effect scope = the sup write (the statement's write target).

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `bdm_acc_loan_info_sup` (the write target @160)
- **Excluded:** `rrcdm_job_log_exec_par` — its statement (@211) does NOT use `iiapty` (it reads `bdm_acc_loan_info_sup` with a `data_dt` filter only) → outside the effect scope. The sup-write statement's other join inputs (p4, rollover_loan_info, `bdm_sys_acc_loan_info`, …) — input tables, excluded (pinned rule).

## 3. L2 ground truth (per script)

### 3.1 Downstream L2 (SUP_M)

The seed `p5.iiapty` is a **JOIN-KEY usage** in the sup-write statement. The flow: `p5.iiapty` (join key) → the statement's output rows → the sup write target fields @160 (DML forward). The join's OTHER keys (`p4.iiapty`, `p5.p_dt`, `p4.p_dt`) are different field instances — the seed zone is `p5.iiapty` only; the walker's seed-zone JOIN rule admits the flow into the statement output. Expected closure: the join-key instance, the statement output, the sup write targets.

### 3.2 Upstream L2

Empty for all scripts (no writers anywhere).

## 4. Edge cases pinned

- ODS source field with no writers → **empty upstream projection** (the first such case in the suite).
- JOIN-key usage counts as a USE (the effect scope includes WHERE, joins, and any usage — user ruling 2026-08-12).
- The effect scope covers only the STATEMENTS that use the field: the rrcdm statement doesn't → its write target stays out.
