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

The downstream flow is the **transitive effect scope** (user ruling 2026-08-12) — the chain runs down to the END. Chain: the seed's join usage @151-152 → the sup-write statement's output rows → the sup write @160 (ALL its write targets — the effect lands on what the statement writes, incl. the literal `data_dt` partition) → the sup `data_dt` read @223 (the rrcdm statement's filter) → the rrcdm write @211. Ends at rrcdm — nothing reads it. Same continuation mechanism as the data_dt seed's probe-pinned chain (R19.2).

- **Scripts:** `BDM_ACC_LOAN_INFO_SUP_M`
- **Tables:** `ods_hie_ipacmsp` (the read instances — the queried table), `bdm_acc_loan_info_sup` (the effect-scope write target @160), `rrcdm_job_log_exec_par` (the chain end @211, via the sup `data_dt` read leg @223)
- **Excluded:** the sup-write statement's other join inputs (p4, rollover_loan_info, `bdm_sys_acc_loan_info`, …) — input tables, excluded (field-level, not statement-level). The other join key `p4.iiapty` is a different field instance — its producers do not enter the seed's effect.

## 3. L2 ground truth (per script)

### 3.1 Downstream L2 (SUP_M)

The seed `p5.iiapty` is a **JOIN-KEY usage** in the sup-write statement. The flow: `p5.iiapty` (join key) → the statement's output rows → the sup write target fields @160 (DML forward — all of them; the effect lands on what the statement writes, incl. the literal `data_dt` partition). The join's OTHER keys (`p4.iiapty`, `p5.p_dt`, `p4.p_dt`) are different field instances — the seed zone is `p5.iiapty` only; the walker's seed-zone JOIN rule admits the flow into the statement output. The chain continues (transitive effect scope): sup.data_dt@160 → (identity) → the sup `data_dt` read @223 in the rrcdm statement (its WHERE filter) → the rrcdm write targets @211 (DML forward). Ends at rrcdm — nothing reads it. Expected closure: the join-key instance, the statement output, the sup write targets, the rrcdm write targets.

### 3.2 Upstream L2

Empty for all scripts (no writers anywhere).

## 4. Edge cases pinned

- ODS source field with no writers → **empty upstream projection** (the first such case in the suite).
- JOIN-key usage counts as a USE (the effect scope includes WHERE, joins, and any usage — user ruling 2026-08-12).
- The effect scope is **transitive to the END**: even though the rrcdm statement doesn't use `iiapty` itself, it uses `sup.data_dt` — a field written under the seed's effect (all write targets of the using statement carry the effect) → the chain continues into the rrcdm write @211.
