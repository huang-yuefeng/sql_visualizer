# Ground Truth — Seed `rrcdm_job_log_exec_par.data_dt` (upstream-only shape, R29)

> **Seed:** `rrcdm_job_log_exec_par.data_dt` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.2/§3.2 REPAIRED 2026-08-12 with probe evidence (repin round: the downstream projection is the writer's own leg, NOT empty — see §3.2)
>
> **CR10 re-derivation status (2026-08-13):** the §3.2 writer's-own-leg closures (RDP1-3 / RDS1-3 / RDD1-3) were REPINNED FROM THE SERVED CLOSURES (probe-pinned, "byte-identical to HEAD") — circular per the CR10 ruling. The independent re-derivation (backend/tests/test_independent_r29_ground_truth.py) re-verifies the closures against the SQL SOURCE TEXT: each script's INSERT INTO TABLE rrcdm_job_log_exec_par(... data_dt ...) target line (PL@253, SUP_M@211, DL@549) and literal write column (`'…' AS data_dt`, PL@254, SUP_M@213, DL@550) are SQL-verifiable, and no script READS the table (the writer's-own-leg shape is SQL-derived). The write-chain rows (data_dt→output, output→rrcdm) are SQL-verifiable; the output-VT membership SCHEMA rows (URP2/URS2/RDP2/RDS2/RDD2) are flagged `pending` in jaccard_canonical.py (Phase-4c rendering convention — must be re-derived before they count as independent ground truth).
>
> **Shape purpose:** the queried field has WRITERS but NO READERS in the workspace — exercises the **upstream-only** writing chain and the **writer's-own-leg downstream** projection.

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

**Writer's own leg (REPAIRED 2026-08-12).** No script READS `rrcdm_job_log_exec_par.data_dt` — but downstream = ALL FIELD_LIKE occurrences of the field, incl. the write-leg partition var (legacy W1 semantics, unchanged; the backend team's 2026-08-12 byte-identity probe, /tmp/diag_byteidentity.py, shows the served downstream closures identical to HEAD, so the original EMPTY pin was wrong — repaired with evidence, never the code). The downstream projection is the writing statement's own 3-node chain (the write column + the statement output + the DML target). The writing statement's FROM reads (`bdm_acc_loan_info`) stay out — different field instance.

## 3. L2 ground truth (per script)

### 3.1 Upstream L2 (per writer script)

The upstream flow = the log statement's `data_dt` write chain only: the literal → `rrcdm_job_log_exec_par.data_dt` (via the statement output / DML routing). NO producing fields (literal-terminated). The statement's other selected columns (object_domain, table_name, total_rows, …) are different fields — not part of this flow. The statement's FROM sources (`bdm_acc_loan_info`) are inputs — excluded.

### 3.2 Downstream L2 (REPAIRED 2026-08-12 — probe-pinned served closures)

The writer's own leg, per script (3 nodes / 3 edges each — the downstream mirror of the §3.1 write chain; the served anchors are the write sites):

| Script | Closure |
|--------|---------|
| BDM_ACC_LOAN_INFO_PL.sql | `data_dt`@254 → output (TABLE_FLOW@254) → `data_dt`@254 (SCHEMA@254) → `rrcdm_job_log_exec_par`@253 (TABLE_FLOW@253 — the write leg) |
| BDM_ACC_LOAN_INFO_SUP_M.sql | `data_dt`@213 → output (TABLE_FLOW@213) → `data_dt`@213 (SCHEMA@213) → `rrcdm_job_log_exec_par`@211 (TABLE_FLOW@211 — the write leg) |
| BDM_ACC_LOAN_INFO_Digitallending.sql | `data_dt`@550 → output (TABLE_FLOW@550) → `data_dt`@550 (SCHEMA@550) → `rrcdm_job_log_exec_par`@549 (TABLE_FLOW@549 — the write leg) |

Evidence: harness probe /tmp/diag_harness_closures.py (served L2 builds, 2026-08-12) + the backend team's byte-identity probe (closures identical to HEAD). The Jaccard harness pins these as rows RDP1-3 / RDS1-3 / RDD1-3 (jaccard_canonical.py point 15).

## 4. Edge cases pinned

- Literal-written field with no readers → the downstream projection is the **writer's own leg** (write column → output → DML target), NOT empty (REPAIRED 2026-08-12 — downstream = all FIELD_LIKE occurrences incl. the write-leg partition var).
- A statement's input tables never carry the seed's flow, even when the statement WRITES the seed field (the log statement reads bdm while writing the log's `data_dt`).
