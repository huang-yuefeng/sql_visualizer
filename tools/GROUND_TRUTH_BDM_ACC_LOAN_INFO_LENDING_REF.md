# Ground Truth — Seed `bdm_acc_loan_info.lending_ref` (both directions, real field chain, R29)

> **Seed:** `bdm_acc_loan_info.lending_ref` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.1/§2.2/§3.1/§3.2 REPAIRED 2026-08-12 with probe evidence (repin round: upstream chain start @426; downstream closure terminates at the loan_final output — see §3.1/§3.2)
>
> **Shape purpose:** the queried field has BOTH writers and readers, and — unlike `data_dt` — the upstream writer is a **REAL field chain** (no literals): the walker's producing logic is exercised in the upstream direction.

## 1. Workspace facts (verified 2026-08-12)

**Writers (one):**
- BDM_ACC_LOAN_INFO_Digitallending.sql @99 — the `INSERT OVERWRITE bdm_acc_loan_info` writes `lending_ref` from the statement output column `A.acctnbr AS LENDING_REF` @101, produced by the `A` alias of `ods_ccb_cb_loan_acctloan` @426 (a real alias/transform chain: ODS field → bdm field). **REPAIRED 2026-08-12:** the chain start is `ods_ccb_cb_loan_acctloan.acnw` @426 (probe-pinned served closure); the doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` @62/@82 instances belong to the `temp_kmbh_gl` CTE segment (see the last §1 bullet) — NOT part of this producing chain.
- BDM_ACC_LOAN_INFO_PL.sql — **0 occurrences** of `lending_ref` (grep-verified): PL writes the TABLE `bdm_acc_loan_info` @19 but NOT this field → PL is not a writer of the seed.

**Readers (one):**
- BDM_ACC_LOAN_INFO_SUP_M.sql — `p1.lending_ref` (p1 = `bdm_acc_loan_info`) used throughout the **sup-write statement**: SELECT outputs @67/@163, join keys @41/@117/@150/@156/@201/@206, `NOT IN` @48. All in the statement whose `INSERT OVERWRITE bdm_acc_loan_info_sup` is @160.
- The rrcdm statement (@211) does NOT use `lending_ref` (its SELECT is literals + COUNT(1), FROM `bdm_acc_loan_info_sup` @223) → outside the effect scope.
- DL's `lending_ref` at @484/@486 is on the `temp_kmbh_gl`/`temp_kmbh_ie` CTE columns, built from `ODS_CUPD_CLD_ACCTMASTER_NEW` (not from bdm) — NOT reads of the seed (verified: the CTE's `p1.acnw AS lending_ref` sources ODS).

## 2. L1 ground truth

### 2.1 Upstream L1 (writing — DEFAULT direction)

The upstream flow is the **transitive writing chain** (user ruling 2026-08-12): the writing fields of writing fields, back-traced to the start. Chain: `ods_ccb_cb_loan_acctloan.acnw` (the `A` alias @426) → `A.acctnbr AS LENDING_REF` @101 → the statement output → the write target @99 → the seed. Terminates at the ODS source (nobody in the workspace writes it). **REPAIRED 2026-08-12:** the chain start is the ODS FROM source @426 (probe-pinned served closure; the `@62/@82 acnw` instances are the `temp_kmbh_gl` segment — different chain).

- **Scripts:** `BDM_ACC_LOAN_INFO_Digitallending`
- **Tables:** `bdm_acc_loan_info` (the DML target), `ods_ccb_cb_loan_acctloan` (the chain start — its `acnw` field writes the seed via the `A` alias)
- **Excluded — the field-vs-table exclusion from the WRITING side:** `BDM_ACC_LOAN_INFO_PL` writes the queried TABLE `bdm_acc_loan_info` @19 but contains 0 occurrences of `lending_ref` — it does not carry the queried field's flow → excluded (the mirror of the SUP_M/BNQXYE reading-side case).

### 2.2 Downstream L1 (reading)

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. **REPAIRED 2026-08-12 (repin round, probe evidence):** the closure is the CTE-zone flow of the seed's instances (the rollover/loan_final segment), terminating at the `loan_final` SELECT output (the TOP0 output VT) and the NOT-IN read target — the seed never lands in `bdm_acc_loan_info_sup`'s write columns, so the D2 field-aware walker does NOT flow it through the sup write leg (same ruling as the iiapty seed). The rrcdm statement is not reached.

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `bdm_acc_loan_info` (the read instances — the queried table), the rollover/loan_final CTEs + their subqueries (`subq`/`subq1`), `bdm_evt_loan_trans` (the NOT-IN read target @52), the statement output VT
- **Excluded (REPAIRED):** `bdm_acc_loan_info_sup` and `rrcdm_job_log_exec_par` — the seed never reaches the sup write columns. Also excluded: the statement's input tables not in the seed's instance flow.

## 3. L2 ground truth (per script)

### 3.1 Upstream L2 (Digitallending)

The writing flow of the seed inside DL. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 6 nodes / 7 edges):** the chain starts at the ODS FROM source `ods_ccb_cb_loan_acctloan` (the `A` alias) @426 — served edges: `A → acctnbr` (SCHEMA@101), `ods → output` (JOIN@101 — the FROM-source admission; the walker's seed-zone JOIN rule, so the upstream invariant bans FILTER/INDIRECT, not JOIN), `output → LENDING_REF` (SCHEMA@101), `ods → A` (ALIAS@426 + REF@426), `A → output` (TABLE_FLOW@426), `output → bdm` (TABLE_FLOW@99 — the write leg). The statement's OTHER ODS inputs and other output columns (MXKMBH, amt, …) are different fields — excluded. The doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` chain start was wrong (probe evidence; the @62/@82 instances are the temp_kmbh_gl segment). **This is the suite's first REAL (non-literal) upstream chain.**

### 3.2 Downstream L2 (SUP_M)

The seed's usages are join keys and SELECT outputs inside the sup-write statement. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 29 nodes / 54 edges):** the closure is the CTE-zone flow of the seed's instances, terminating at the `loan_final` SELECT output (the TOP0 output VT) and the NOT-IN read target `bdm_evt_loan_trans` @52 — the seed never reaches the sup write columns (D2 field-aware DML, same ruling as iiapty), so the sup write @160 and the rrcdm write @211 are NOT in the closure. The served instance line set is 13/16/22/26/29/41/50/52/67/84/117/150 (per-(field, statement) admission dedup — the doc's §1 lines @48/@156/@163/@201/@206 do not render; the NOT-IN side renders as the REF@52 read of `bdm_evt_loan_trans`). Served forms: JOIN@41/@67/@117/@150 (the rollover/loan_final join keys), REF@16/@22/@29/@41/@52/@84/@117/@150 (reads), TABLE_FLOW@9/@16/@22/@26/@29/@64/@84 (CTE FROM hops + output admissions), SCHEMA@13/@22/@26/@41/@50 (membership), ALIAS@29/@84 (bdm → p1), plus two edgeless truncated-CONCAT expression nodes and an edgeless data_dt. The Jaccard harness pins these as rows LFS1-54 (jaccard_canonical.py point 15).

## 4. Edge cases pinned

- Field-vs-table exclusion on the **writing side** (PL writes the table, not the field → excluded) — the mirror image of the SUP_M/BNQXYE reading-side case.
- The upstream scope is the **transitive writing chain** (writers of writers, back to the start): the chain start `ods_ccb_cb_loan_acctloan` (the `A` alias, carrying `acnw`) is IN the projection even though no script writes it — the chain terminates there (user ruling 2026-08-12). **REPAIRED 2026-08-12:** the chain start is the ODS FROM source @426 (probe evidence) — the doc's earlier `ODS_CUPD_CLD_ACCTMASTER_NEW` @62/@82 reading was the temp_kmbh_gl segment, not this chain. A write statement's unrelated input tables are NOT in the chain and stay out.
- A real producer chain (acnw → lending_ref) must be followed by the upstream walker (ALIAS/TRANSFORM + DML forward); the FROM-source admission into the statement output is typed JOIN (the walker's seed-zone JOIN rule — the upstream invariant bans FILTER/INDIRECT, not JOIN).
- The downstream closure is the **seed-zone instance flow** (REPAIRED 2026-08-12): the seed never reaches the sup write columns, so the closure terminates at the loan_final SELECT output / the NOT-IN read target — the earlier "all write targets of the using statement carry the effect → the chain continues into the rrcdm write @211" reading is FALSE for `lending_ref` (the continuation exists only for fields that land in the write's columns, e.g. the sup/data_dt seed chain of R19.2).
- CTE/temp columns derived from OTHER tables with the same column name (`temp_kmbh_gl.lending_ref`) are NOT the seed — instance identity matters.
