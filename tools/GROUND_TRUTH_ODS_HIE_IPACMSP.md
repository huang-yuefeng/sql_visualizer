# Ground Truth — Seed `ods_hie_ipacmsp.iiapty` (downstream-only shape, R29)

> **Seed:** `ods_hie_ipacmsp.iiapty` | **Workspace:** `samples/sql_sample_v1/` (3 scripts) | **Date:** 2026-08-12 | **Status:** DEFINED (R29) — §2.2/§3.1 REPAIRED 2026-08-12 with probe evidence (repin round: the effect chain terminates at the statement output VT — see §3.1)
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

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. **REPAIRED 2026-08-12 (repin round, probe evidence):** the chain terminates at the sup-write statement's output — `iiapty` is a JOIN KEY of the statement's SELECT and never lands in `bdm_acc_loan_info_sup`'s write columns, so the D2 field-aware walker does NOT flow it through the write leg (a field that doesn't reach a write's columns does not flow through that write). Chain: the seed's join usage @151-152 → the statement's output rows (the TOP0 output VT). Ends there — the effect's continuing carriers are the statement's OWN output columns, and `iiapty` is not among them.

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `ods_hie_ipacmsp` (the read instance — the queried table), the `p5` alias node, `loan_final` (the statement's SELECT source CTE), the statement output VT
- **Excluded (REPAIRED):** `bdm_acc_loan_info_sup` and `rrcdm_job_log_exec_par` — the seed never reaches the sup write columns, so the sup write @160 and the rrcdm write @211 are NOT in the closure. Also excluded: the statement's other join inputs (p4, rollover_loan_info, `bdm_sys_acc_loan_info`, …) and the other join key `p4.iiapty` (a different field instance).

## 3. L2 ground truth (per script)

### 3.1 Downstream L2 (SUP_M)

The seed `p5.iiapty` is a **JOIN-KEY usage** in the sup-write statement. **REPAIRED 2026-08-12 (repin round, probe-pinned served closure — 5 nodes / 6 edges):** the flow is the seed-zone admission into the statement output; the D2 field-aware ruling (a field that doesn't reach a write's columns does NOT flow through the write leg) stops the chain at the TOP0 output VT. Served closure: `iiapty` (the p5 join-key instance, incident lines 151/153) — the `p5` alias of `ods_hie_ipacmsp` (ALIAS@151) — `iiapty → p5` (REF@151) — `p5 → loan_final` FROM hop (TABLE_FLOW@151) — the seed-zone `iiapty → loan_final` JOIN@153 — `loan_final → output` (TABLE_FLOW@64) — `p5 → iiapty` membership (SCHEMA@153). The join's OTHER keys (`p4.iiapty`, `p5.p_dt`, `p4.p_dt`) are different field instances. The Jaccard harness pins these as rows IID1-6 (jaccard_canonical.py point 15).

### 3.2 Upstream L2

Empty for all scripts (no writers anywhere).

## 4. Edge cases pinned

- ODS source field with no writers → **empty upstream projection** (the first such case in the suite).
- JOIN-key usage counts as a USE (the effect scope includes WHERE, joins, and any usage — user ruling 2026-08-12).
- **REPAIRED 2026-08-12:** a join-key seed that never reaches the write's columns does NOT continue through the write leg — the chain terminates at the using statement's output VT (D2 field-aware DML). The earlier "all write targets of the using statement carry the effect → the chain continues into the rrcdm write @211" reading is FALSE for `iiapty` (the continuation exists only for fields that land in the write's columns, e.g. the sup/data_dt seed chain of R19.2).
