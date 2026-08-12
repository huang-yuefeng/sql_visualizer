# Ground Truth — Seed `rrcdm_job_log_exec_par.data_dt` (upstream-only shape, R29)

> **Seed:** `rrcdm_job_log_exec_par.data_dt` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — ground truth built before coding; implementation pending
>
> **Shape purpose:** the queried field has WRITERS but NO READERS in the workspace — exercises the **upstream-only** case and the **EMPTY downstream projection**.

## 1. Workspace facts (verified 2026-08-12)

`rrcdm_job_log_exec_par` is a job-log sink table. `data_dt` is written by all three scripts, always from a LITERAL; **nobody reads the table** (grep for `rrcdm_job_log_exec_par` across the workspace shows only the three INSERT INTO TABLE sites).

| Script | Write | Written value |
|--------|-------|---------------|
| BDM_ACC_LOAN_INFO_PL.sql | INSERT @253, `data_dt` @254 | literal `'${load_date}'` |
| BDM_ACC_LOAN_INFO_Digitallending.sql | INSERT @549, `data_dt` @550 | literal `'$(load_date)'` |
| BDM_ACC_LOAN_INFO_SUP_M.sql | INSERT @211, `data_dt` @213 | literal `'$(load_date)'` |

The log statements read `bdm_acc_loan_info` in their FROM (PL@262, DL@558, SUP_M@223) — those are INPUT tables of the writing statements, not carriers of this seed's flow (input tables stay OUT, pinned rule 2026-08-12).

## 2. L1 ground truth

### 2.1 Upstream L1 (writing — DEFAULT direction)

The fields writing `data_dt` are all literals → the writing flow **terminates at the three writes** (no producing fields, no further tables). The transitive chain rule (user ruling 2026-08-12 — writers of writers, back to the start) applies and terminates immediately: the writers are literals, so there is no second hop.

- **Scripts:** `BDM_ACC_LOAN_INFO_PL`, `BDM_ACC_LOAN_INFO_Digitallending`, `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `rrcdm_job_log_exec_par` (the DML target carrying the write field)
- **Excluded:** `bdm_acc_loan_info` and any other table the log statements read (inputs of the using statements); the scripts' OTHER statements (e.g. PL's bdm write@19) — they do not write this field.

### 2.2 Downstream L1 (reading)

**EMPTY projection.** No script reads `rrcdm_job_log_exec_par.data_dt` (or the table at all). L1 must render an empty directional flow as a clear "no reading flow" state (message, not an error) — the L2 not-in-flow response (R22.3) is the precedent.

## 3. L2 ground truth (per script)

### 3.1 Upstream L2 (per writer script)

The upstream flow = the log statement's `data_dt` write chain only: the literal → `rrcdm_job_log_exec_par.data_dt` (via the statement output / DML routing). NO producing fields (literal-terminated). The statement's other selected columns (object_domain, table_name, total_rows, …) are different fields — not part of this flow. The statement's FROM sources (`bdm_acc_loan_info`) are inputs — excluded.

### 3.2 Downstream L2

Empty for all scripts (no readers anywhere).

## 4. Edge cases pinned

- Literal-written field with no readers → **empty downstream projection** (the first such case in the suite).
- A statement's input tables never carry the seed's flow, even when the statement WRITES the seed field (the log statement reads bdm while writing the log's `data_dt`).
