# sql_sample_v1 — BDM_ACC_LOAN_INFO_SUP_M (ODPS repro script)

**Provenance**: Reconstructed on 2026-08-06 via OCR from user screenshots
(`~/Pictures/Screenshots/code1.png` + `code2.png`) — a MaxCompute/ODPS-dialect
script. The user's real script lives in their workspace; this copy is a
byte-accurate-as-possible reproduction used as a regression test case.

**Dialect markers**: `SET odps.sql.decimal.odps2 = true;` · `INSERT OVERWRITE
TABLE ... PARTITION(...)` · `$(load_date)` · `DATEADD(DATE'...',-1,'DD')` ·
`NVL()` · `LPAD()` · `getdate()` · `--**` header comment block.

**Structure**: header `--**` block, 2 CTEs (`rollover_loan_info`,
`loan_final`), `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup ... SELECT ...`
(target: `bdm_acc_loan_info_sup`), `INSERT INTO rrcdm_job_log_exec_par`
(job log).

## Ground-truth numbers (v3.3.135 extractor)

- Variables: **344** · Dependencies: **1102**
- `bdm_acc_loan_info` appears in **4 contexts** (no-alias CTE FROM, `p1` CTE
  join, subquery `p1`, NOT IN subquery) — the multi-context same-table case
- Other tables: `bdm_acc_loan_info_sup` (INSERT target), `bdm_evt_loan_trans`,
  `bdm_gdc_label_fin`, `bdm_sys_acc_loan_info`, `ods_hub_lsacmsp` (×4),
  `ods_hub_ssclmtp`, `ods_hie_ipblmsp`, `ods_hie_ipdcmsp`, `ods_hie_ippdcpp`,
  `ods_hie_ipacmsp`, `ods_cdp_gdc_acct_migrate_to_diff_branches`,
  `rrcdm_job_log_exec_par`
- Key fields: `lending_ref`, `loan_maturity_dt`, `p1.reserved_field8`
  (rollover marker per HBCNRDQE-5243/5244 comment)

## Regression purpose

1. **Issue a — L2 table dedup**: same physical table (`bdm_acc_loan_info`) in
   4 contexts must render as ONE L2 node with all context edges passing
   through it.
2. **Issues b/c — data-flow participation**: `ABROAD_LOAD_PURPOSE` is
   deliberately NOT queried by this script. Searching
   `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE` must NOT match this script (search
   no_matches; L2 "not in data flow" state) — never the old 5-node/0-edge
   skeleton.
3. Extractor smoke regression: 344 vars / 1102 deps, table+field invariants.

## Local use

- **Upload into the app**: zip this folder (`cd samples/sql_sample_v1 && zip
  ../sql_sample_v1.zip *.sql README.md`) and upload as a workspace; scan +
  index it, then search `bdm_acc_loan_info.ABROAD_LOAD_PURPOSE` (expect no
  matches) or open the script's L2 with filter on any of its real fields
  (`lending_ref`, `loan_maturity_dt`) to exercise the flow.
- **Backend tests**: `backend/tests/test_dataflow/test_sample_v1_repro.py`
  (run via `docker exec -w /app/backend gps-sql-backend python3 -m pytest
  tests/test_dataflow/test_sample_v1_repro.py -v`).
