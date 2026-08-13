# Ground Truth — Seed `bdm_acc_loan_info.lending_ref` (both directions, real field chain, R29)

> **Seed:** `bdm_acc_loan_info.lending_ref` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.1/§2.2/§3.1/§3.2 REPAIRED 2026-08-12 with probe evidence (repin round: upstream chain start @426; downstream row-level-continuation closure runs through the sup write @160 to the rrcdm write @211 — see §3.1/§3.2)
>
> **Shape purpose:** the queried field has BOTH writers and readers, and — unlike `data_dt` — the upstream writer is a **REAL field chain** (no literals): the walker's producing logic is exercised in the upstream direction.

## 1. Workspace facts (verified 2026-08-12)

**Writers (one):**
- BDM_ACC_LOAN_INFO_Digitallending.sql @99 — the `INSERT OVERWRITE bdm_acc_loan_info` writes `lending_ref` from the statement output column `A.acctnbr AS LENDING_REF` @101, produced by the `A` alias of `ods_ccb_cb_loan_acctloan` @426 (a real alias/transform chain: ODS field → bdm field). **REPAIRED 2026-08-12:** the chain start is `ods_ccb_cb_loan_acctloan.acctnbr` @426 (probe-pinned served closure); the doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` @62/@82 instances belong to the `temp_kmbh_gl` CTE segment (see the last §1 bullet) — NOT part of this producing chain.
- BDM_ACC_LOAN_INFO_PL.sql — **0 occurrences** of `lending_ref` (grep-verified): PL writes the TABLE `bdm_acc_loan_info` @19 but NOT this field → PL is not a writer of the seed.

**Readers (one):**
- BDM_ACC_LOAN_INFO_SUP_M.sql — `p1.lending_ref` (p1 = `bdm_acc_loan_info`) used throughout the **sup-write statement**: SELECT outputs @67/@163, join keys @41/@117/@150/@156/@201/@206, `NOT IN` @48. All in the statement whose `INSERT OVERWRITE bdm_acc_loan_info_sup` is @160.
- The rrcdm statement (@211) does NOT use `lending_ref` directly (its SELECT is literals + COUNT(1), FROM `bdm_acc_loan_info_sup` @223) — but its ROW-SELECTION filters `sup.data_dt` @225, a column the sup write produced, so the row-level continuation (user ruling 2026-08-12) carries the effect through the sup read into the rrcdm write @211.
- DL's `lending_ref` at @484/@486 is on the `temp_kmbh_gl`/`temp_kmbh_ie` CTE columns, built from `ODS_CUPD_CLD_ACCTMASTER_NEW` (not from bdm) — NOT reads of the seed (verified: the CTE's `p1.acnw AS lending_ref` sources ODS).

## 2. L1 ground truth

### 2.1 Upstream L1 (writing — DEFAULT direction)

The upstream flow is the **transitive writing chain** (user ruling 2026-08-12): the writing fields of writing fields, back-traced to the start. Chain: `ods_ccb_cb_loan_acctloan.acctnbr` (the `A` alias @426) → `A.acctnbr AS LENDING_REF` @101 → the statement output → the write target @99 → the seed. Terminates at the ODS source (nobody in the workspace writes it). **REPAIRED 2026-08-12:** the chain start is the ODS FROM source @426 (probe-pinned served closure; the `@62/@82 acnw` instances are the `temp_kmbh_gl` segment — different chain).

- **Scripts:** `BDM_ACC_LOAN_INFO_Digitallending`
- **Tables:** `bdm_acc_loan_info` (the DML target), `ods_ccb_cb_loan_acctloan` (the chain start — its `acctnbr` field writes the seed via the `A` alias)
- **Excluded — the field-vs-table exclusion from the WRITING side:** `BDM_ACC_LOAN_INFO_PL` writes the queried TABLE `bdm_acc_loan_info` @19 but contains 0 occurrences of `lending_ref` — it does not carry the queried field's flow → excluded (the mirror of the SUP_M/BNQXYE reading-side case).

### 2.2 Downstream L1 (reading)

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. **REPAIRED 2026-08-12 (repin round, probe evidence — row-level continuation):** the sup-write statement USES the seed (join keys + SELECT outputs @41/@117/@150/@156/@201/@206), so the effect rides its output ROWS and flows into ALL its write targets — `bdm_acc_loan_info_sup` @160 — even though `lending_ref` is not among the written columns (the rows selected by the join keys ARE the write's rows). The rrcdm statement then filters `sup.data_dt` @225 — a column the sup write produced — so its row-selection continues the chain into its write target `rrcdm_job_log_exec_par` @211. Chain: seed join-key usages → sup write @160 → sup data_dt read @225 → rrcdm write @211.

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `bdm_acc_loan_info` (the read instances — the queried table), the rollover/loan_final CTEs + their subqueries (`subq`/`subq1`), `bdm_evt_loan_trans` (the NOT-IN read target @52), `bdm_acc_loan_info_sup` (the using statement's write target @160), `rrcdm_job_log_exec_par` (the continuation write @211)
- **Excluded:** the statement's input tables not in the seed's instance flow (they are not part of the seed's flow).

## 3. L2 ground truth (per script)

### 3.1 Upstream L2 (Digitallending)

The writing flow of the seed inside DL. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 6 nodes / 7 edges):** the chain starts at the ODS FROM source `ods_ccb_cb_loan_acctloan` (the `A` alias) @426 — served edges: `A → acctnbr` (SCHEMA@101), `ods → output` (JOIN@101 — the FROM-source admission; the walker's seed-zone JOIN rule, so the upstream invariant bans FILTER/INDIRECT, not JOIN), `output → LENDING_REF` (SCHEMA@101), `ods → A` (ALIAS@426 + REF@426), `A → output` (TABLE_FLOW@426), `output → bdm` (TABLE_FLOW@99 — the write leg). The statement's OTHER ODS inputs and other output columns (MXKMBH, amt, …) are different fields — excluded. The doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` chain start was wrong (probe evidence; the @62/@82 instances are the temp_kmbh_gl segment). **This is the suite's first REAL (non-literal) upstream chain.**

### 3.2 Downstream L2 (SUP_M)

The seed's usages are join keys and SELECT outputs inside the sup-write statement. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 37 nodes / 79 edges / 21 highlight lines):** the row-level continuation (user ruling) carries the effect through the sup write into the rrcdm statement. The closure has two segments:

- **CTE-zone seed flow** (unchanged): the rollover/loan_final segment — seed instances @41/@67/@117/@150 as join keys and SELECT outputs, the `bdm_evt_loan_trans` NOT-IN read target @52 (REF@52), the CTE FROM hops + output admissions (TABLE_FLOW@9/@16/@22/@26/@29/@64/@84), membership SCHEMA@13/@22/@26/@41/@50, bdm→p1 ALIAS@29/@84, plus two edgeless truncated-CONCAT expression nodes and an edgeless data_dt. Served forms: JOIN@41/@67/@117/@150, REF@16/@22/@29/@41/@52/@84/@117/@150.
- **The sup-write continuation** (NEW): the using statement's write leg into `bdm_acc_loan_info_sup` (TABLE_FLOW@160, stmt TOP0), its self-CTE source `p2` @199 (SCHEMA@201/@202/@203 — the written columns `lending_ref`/`data_dt`/`charge_department`), the rrcdm statement's read of sup's rows (TABLE_FLOW@223 — admitted as a row-selection continuation because its @225 `sup.data_dt` filter uses a column the sup write produced; stmt TOP1) and the rrcdm write (TABLE_FLOW@211).

The served instance line set is 9/13/16/22/26/29/41/50/52/64/67/84/117/150/160/199/201/202/203/211/223 (21 highlight lines). The Jaccard harness pins these as rows LFS1-79 (jaccard_canonical.py point 15).

## 4. Edge cases pinned

- Field-vs-table exclusion on the **writing side** (PL writes the table, not the field → excluded) — the mirror image of the SUP_M/BNQXYE reading-side case.
- The upstream scope is the **transitive writing chain** (writers of writers, back to the start): the chain start `ods_ccb_cb_loan_acctloan` (the `A` alias, carrying `acctnbr`) is IN the projection even though no script writes it — the chain terminates there (user ruling 2026-08-12). **REPAIRED 2026-08-12:** the chain start is the ODS FROM source @426 (probe evidence) — the doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW` @62/@82 reading was the temp_kmbh_gl segment, not this chain. A write statement's unrelated input tables are NOT in the chain and stay out.
- A real producer chain (acctnbr → lending_ref) must be followed by the upstream walker (ALIAS/TRANSFORM + DML forward); the FROM-source admission into the statement output is typed JOIN (the walker's seed-zone JOIN rule — the upstream invariant bans FILTER/INDIRECT, not JOIN).
- **Row-level continuation (REPAIRED 2026-08-12, user ruling):** the statement that USES the queried field carries the effect into ALL its write targets — even when the seed is not among the written columns, because the SELECTED ROWS are the rows selected by the seed's join keys / outputs (sup write @160). A later statement whose ROW-SELECTION uses a column the write produced (the rrcdm statement's `sup.data_dt` filter @225) continues the chain into ITS write targets (@211). The pre-repin "stops at the loan_final output / NOT-IN target" reading is superseded — the lending_ref chain runs to rrcdm@211.
- CTE/temp columns derived from OTHER tables with the same column name (`temp_kmbh_gl.lending_ref`) are NOT the seed — instance identity matters.
