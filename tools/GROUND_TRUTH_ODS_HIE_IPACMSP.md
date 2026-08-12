# Ground Truth — Seed `ods_hie_ipacmsp.iiapty` (downstream-only shape, R29)

> **Seed:** `ods_hie_ipacmsp.iiapty` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.2/§3.1/§4 REPAIRED 2026-08-12 with probe evidence (repin round: the row-level-continuation chain runs to the rrcdm write @211 — see §2.2/§3.1)
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

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. **REPAIRED 2026-08-12 (repin round, probe evidence — row-level continuation):** the using statement's SELECT ROWS are selected BY the join key, so the effect rides the statement's output ROWS and flows into ALL its write targets — even though `iiapty` itself is not among `bdm_acc_loan_info_sup`'s written columns (the user's row-level ruling: "the selection of rows are from the queried field"). The rrcdm statement then filters `sup.data_dt` @225 — a column the sup write produced — so its row-selection continues the chain into its write target `rrcdm_job_log_exec_par` @211. Chain: seed join usage @151-153 → sup write @160 → sup data_dt read @225 → rrcdm write @211.

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `ods_hie_ipacmsp` (the read instance — the queried table), `bdm_acc_loan_info_sup` (the using statement's write target @160), `rrcdm_job_log_exec_par` (the continuation write @211)
- **Excluded:** `bdm_acc_loan_info` — the statement's other join inputs (p4, rollover_loan_info, `bdm_sys_acc_loan_info`, …) and the other join key `p4.iiapty` (a different field instance) — they are not in the seed's instance flow.

## 3. L2 ground truth (per script)

### 3.1 Downstream L2 (SUP_M)

The seed `p5.iiapty` is a **JOIN-KEY usage** in the sup-write statement. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 13 nodes / 17 edges / 10 highlight lines):** the row-level continuation (user ruling) carries the effect through the sup write into the rrcdm statement. Served closure: the seed zone @151-153 (`iiapty` — the p5 join-key instance — `p5` alias of `ods_hie_ipacmsp`, `loan_final`: ALIAS@151 / REF@151 / TABLE_FLOW@151 / JOIN@153 / SCHEMA@153) → the sup-write statement's output VT `⟐output` @64 (TABLE_FLOW@64) → its write leg into `bdm_acc_loan_info_sup` (TABLE_FLOW@160; the statement's self-CTE source `p2` @199 with the written columns `lending_ref`/`data_dt`/`charge_department` via SCHEMA@201/@202/@203 and the seed-zone JOIN@203) → the rrcdm statement's read of sup's rows (TABLE_FLOW@223 — admitted as a row-selection continuation because its @225 `sup.data_dt` filter uses a column the sup write produced) → the rrcdm write (TABLE_FLOW@211, stmt TOP1). The join's OTHER keys (`p4.iiapty`, `p5.p_dt`, `p4.p_dt`) are different field instances. The Jaccard harness pins these as rows IID1-17 (jaccard_canonical.py point 15); highlight lines: 64/151/153/160/199/201/202/203/211/223.

### 3.2 Upstream L2

Empty for all scripts (no writers anywhere).

## 4. Edge cases pinned

- ODS source field with no writers → **empty upstream projection** (the first such case in the suite).
- JOIN-key usage counts as a USE (the effect scope includes WHERE, joins, and any usage — user ruling 2026-08-12).
- **Row-level continuation (REPAIRED 2026-08-12, user ruling):** the statement that USES the queried field carries the effect into ALL its write targets — even when the seed is not among the written columns, because the SELECTED ROWS are the rows selected by the seed (join key @151 → sup write @160). A later statement whose ROW-SELECTION uses a column the write produced (the rrcdm statement's `sup.data_dt` filter @225) continues the chain into ITS write targets (@211). The pre-repin "stops at the statement output VT" reading is superseded — the iiapty chain runs to rrcdm@211.
