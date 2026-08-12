# Ground Truth — Seed `bdm_acc_loan_info.lending_ref` (both directions, real field chain, R29)

> **Seed:** `bdm_acc_loan_info.lending_ref` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — ground truth built before coding; implementation pending
>
> **Shape purpose:** the queried field has BOTH writers and readers, and — unlike `data_dt` — the upstream writer is a **REAL field chain** (no literals): the walker's producing logic is exercised in the upstream direction.

## 1. Workspace facts (verified 2026-08-12)

**Writers (one):**
- BDM_ACC_LOAN_INFO_Digitallending.sql @99 — the `INSERT OVERWRITE bdm_acc_loan_info` writes `lending_ref` from `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` (`SELECT p1.acnw AS lending_ref`, lines 62/82 — a real alias/transform chain: ODS field → bdm field).
- BDM_ACC_LOAN_INFO_PL.sql — **0 occurrences** of `lending_ref` (grep-verified): PL writes the TABLE `bdm_acc_loan_info` @19 but NOT this field → PL is not a writer of the seed.

**Readers (one):**
- BDM_ACC_LOAN_INFO_SUP_M.sql — `p1.lending_ref` (p1 = `bdm_acc_loan_info`) used throughout the **sup-write statement**: SELECT outputs @67/@163, join keys @41/@117/@150/@156/@201/@206, `NOT IN` @48. All in the statement whose `INSERT OVERWRITE bdm_acc_loan_info_sup` is @160.
- The rrcdm statement (@211) does NOT use `lending_ref` (its SELECT is literals + COUNT(1), FROM `bdm_acc_loan_info_sup` @223) → outside the effect scope.
- DL's `lending_ref` at @484/@486 is on the `temp_kmbh_gl`/`temp_kmbh_ie` CTE columns, built from `ODS_CUPD_CLD_ACCTMASTER_NEW` (not from bdm) — NOT reads of the seed (verified: the CTE's `p1.acnw AS lending_ref` sources ODS).

## 2. L1 ground truth

### 2.1 Upstream L1 (writing — DEFAULT direction)

The upstream flow is the **transitive writing chain** (user ruling 2026-08-12): the writing fields of writing fields, back-traced to the start. Chain: `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` → `lending_ref` (DL@99) → the seed. Terminates at the ODS source (nobody in the workspace writes it).

- **Scripts:** `BDM_ACC_LOAN_INFO_Digitallending`
- **Tables:** `bdm_acc_loan_info` (the DML target), `ODS_CUPD_CLD_ACCTMASTER_NEW` (the chain start — its `acnw` field writes the seed)
- **Excluded — the field-vs-table exclusion from the WRITING side:** `BDM_ACC_LOAN_INFO_PL` writes the queried TABLE `bdm_acc_loan_info` @19 but contains 0 occurrences of `lending_ref` — it does not carry the queried field's flow → excluded (the mirror of the SUP_M/BNQXYE reading-side case).

### 2.2 Downstream L1 (reading)

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. Chain: the seed's read instances (`p1.lending_ref`) → the sup-write statement (uses `lending_ref`) → the sup write @160 (ALL its write targets — the effect lands on what the statement writes, incl. the literal `data_dt` partition) → the sup `data_dt` read @223 (the rrcdm statement's filter) → the rrcdm write @211. Ends at rrcdm — nothing reads it. Same continuation mechanism as the data_dt seed's probe-pinned chain (R19.2).

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `bdm_acc_loan_info` (the read instances — the queried table), `bdm_acc_loan_info_sup` (the effect-scope write target @160), `rrcdm_job_log_exec_par` (the chain end @211, via the sup `data_dt` read leg @223)
- **Excluded:** the sup-write statement's input tables (ODS sources, p2/p3 joins) — inputs, excluded (field-level, not statement-level).

## 3. L2 ground truth (per script)

### 3.1 Upstream L2 (Digitallending)

The writing flow of the seed inside DL: `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` (p1.acnw) → (alias/transform `AS lending_ref`, CTE outputs) → the write target `bdm_acc_loan_info.lending_ref` @99 (DML forward). The statement's OTHER ODS inputs (ODS_HUB_SSALSFP, …) and other output columns (MXKMBH, amt, …) are different fields — excluded. **This is the suite's first REAL (non-literal) upstream chain.**

### 3.2 Downstream L2 (SUP_M)

The seed's usages are join keys and SELECT outputs inside the sup-write statement → the flow: `p1.lending_ref` instances → the statement's output rows → the sup write target fields @160 (all of them — the effect lands on what the statement writes, incl. the literal `data_dt` partition). The chain continues (transitive effect scope): sup.data_dt@160 → (identity) → the sup `data_dt` read @223 in the rrcdm statement (its WHERE filter) → the rrcdm write targets @211 (DML forward). Ends at rrcdm — nothing reads it.

## 4. Edge cases pinned

- Field-vs-table exclusion on the **writing side** (PL writes the table, not the field → excluded) — the mirror image of the SUP_M/BNQXYE reading-side case.
- The upstream scope is the **transitive writing chain** (writers of writers, back to the start): the chain start `ODS_CUPD_CLD_ACCTMASTER_NEW` (carrying `acnw`) is IN the projection even though no script writes it — the chain terminates there (user ruling 2026-08-12). A write statement's unrelated input tables are NOT in the chain and stay out.
- A real producer chain (acnw → lending_ref) must be followed by the upstream walker (ALIAS/TRANSFORM + DML forward).
- The downstream chain is **transitive to the END**: the sup write's literal `data_dt` target (admitted with all write targets of the using statement) continues the chain through the rrcdm statement's sup `data_dt` read @223 into the rrcdm write @211 — the same mechanism as the probe-pinned data_dt chain (R19.2).
- CTE/temp columns derived from OTHER tables with the same column name (`temp_kmbh_gl.lending_ref`) are NOT the seed — instance identity matters.
