# Ground Truth — BDM_ACC_LOAN_INFO_Digitallending.sql

Hand-verified data flow of `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_Digitallending.sql`
(562 lines; the script's own job name is `BDM_ACC_LOAN_INFO_Digitallending` —
stmt2 L554, and the vim title of the source screenshots). This is the
reference for future work: every extractor / graph / highlight change must
preserve these flows. The REQUIREMENT sections (§4.2 LAYER-2, §4.3 MISSING)
are the authoritative source for the benchmark fixture B (user ruling
J12-13, 2026-08-11 — "strictly use the ground truth in the benchmark": B is
derived from the doc's REQUIREMENT sections, never from the engine's emitted
form). The §8.5 closure table is the probe-pinned machine-readable
realization of those requirements (the engine's served L2 form, pinned
AFTER the requirements were written — the pin records how the served output
realizes the requirements, it never redefines them).

**CURRENT-STATE RE-VERIFICATION (2026-08-12, Digitallending round): the
script was reconstructed from the original screenshots (code3-1..5 —
`~/Pictures/Screenshots/` and `screenshots/` in this repo) by line-by-line
OCR; every line number below was verified against the pixel geometry of the
screenshots (y-anchor: L57 WITH at y805.5, L58 at y820, 14px pitch →
L76 `where t.rn = 1` at y1072, L78 `temp_kmbh_ie as (` at y1099.5, L99
INSERT OVERWRITE at y1392.5 — the raw tesseract pass at 0.85-0.92
confidence). The G2 team's file landed 2026-08-12 (562 lines, 21,411
bytes); line numbers and structure were diffed against it and match
exactly — see RECONCILIATION STATUS below. This doc's line numbers
reference the FINAL file. OCR caveats (none flow-critical): the CTE names
and their join aliases read as `temp_kmbh_gl`/`temp_kmbh_ie` and
`km_gl`/`km_ie` (raw tesseract 0.87-0.92 + rapidocr + the reconstruction
agent's pixel work all read `gl`; a noisier pass read `g1`) — CONFIRMED
by the landed file (L58/L78, L483/L485, L111); the load-date literal: the
raw OCR passes read the braces form `'${load_date}'` (bulk code3-4 L407)
while the landed file writes `'$(load_date)'` — this doc uses the file's
form, the spelling is flow-irrelevant (the closure seeds are on data_dt);
stmt2's INSERT column list (L549) was truncated by the OCR — resolved by
the file (9 columns: data_dt, object_domain, sub_src_system, table_name,
job_name, total_rows, load_time, STATUS, remarks). [PENDING-PROBE items
below are filled by the probe run; the REQUIREMENT lines themselves
(§4.2/§4.3) hold regardless of what the engine emits.]**

**RECONCILIATION STATUS (2026-08-12 — diffed against the FINAL file
`samples/sql_sample_v1/BDM_ACC_LOAN_INFO_Digitallending.sql`, 562 lines,
21,411 bytes): line numbers and statement structure MATCH EXACTLY** — L77
`),` on its own line, L99 INSERT OVERWRITE, CTEs `temp_kmbh_gl` L58-77 /
`temp_kmbh_ie` L78-97, joins L427-543 with L450-453/L493-500/L501-503
commented, L544 WHERE, L545 `;`, stmt2 L549-562; the file parses with
sqlglot mysql (verified 2026-08-12: 3 statements = SET + 2 DML). The
risky-spot flags resolved as follows:
1. **L77 `),` own line — VERIFIED MATCH** (file L77; CTE2 name at L78).
2. **L407 internal-counterparty branch — VERIFIED MATCH**: file L407
   `WHEN EXISTS (SELECT 1 FROM BDM_ACC_INTERNAL_COUNTERPARTY WHERE
   data_dt = '$(load_date)' AND acct_no = P1.dkrzzh) THEN 'NI'`; the bulk
   OCR draft (code3-4, line 83) reads the same branch with `THEN 'NI'` —
   consistent with the DM_FLAG2 CASE's I/NI values (this doc's earlier
   'N' was a misread). All line numbers below L407 confirmed.
3. **CTE names / aliases — VERIFIED MATCH**: `temp_kmbh_gl` L58,
   `temp_kmbh_ie` L78, aliases `km_gl`/`km_ie` L483/L485, L111
   `NVL(km_gl.MXKMBH, km_ie.MXKMBH)` — the `gl` reading confirmed.
4. **L545 `;` boundary — VERIFIED MATCH** (L545 `;`, blank L546-547,
   comment L548, stmt2 L549-562; L549 = 9-column INSERT column list —
   the OCR-truncated paren resolved).
5. **Load-date literal — FILE FORM `'$(load_date)'` (parens)**; the raw
   OCR passes read the braces form `'${load_date}'` (bulk code3-4 L407).
   This doc writes the file's parens form; flow-irrelevant (closure seeds
   are on data_dt).

**RECONSTRUCTION DEVIATIONS (file differs from the SOURCE screenshots —
flow-irrelevant, none carries bdm_acc_loan_info.data_dt; the benchmark
team may want them fixed in the file):**
- **(a) L106** `,t_branch.org_no AS ORG_NO` — ACTIVE in the file; the
  SOURCE has the column COMMENTED OUT (raw-pass x-coordinate: the leading
  comma sits at x97.5, the shifted-right old-generation column, vs the
  active column x88.5-90.5; the active ORG_NO is the literal
  'CNHSBC900' at L107). The t_branch join L501-503 is commented in BOTH.
- **(b) L278-289 150-block** — the K/L/I/CASE/END lines L278/280/282/
  284/285/286/287 are ACTIVE in the file; the SOURCE has them COMMENTED
  OUT (their commas sit at x98.5-110.5 — the old-generation column — vs
  the active column x88-89.5 of L281/288/289/290; the p1/p2-based SUBSTR
  lines L279/281/283/288/289 are active in BOTH). The L490 comment
  `--150添加维护原始到期日` is an inline comment in both.
- **(c) L491** — the file rewrites the source's MaxCompute-style
  `date_add('$(load_date)', -1)` as `date_add('$(load_date)', INTERVAL
  -1 DAY)` (sqlglot-mysql parse fix; same "yesterday" semantics).
- **(d) L283** — `SUBSTR(p1.GXRQ, 1,4)...` in both file and source (the
  reconstruction notes' p1/p2 uncertainty resolved to p1).

> **WAIT-CONDITION NOTE (2026-08-12, updated):** the file-exists AND
> parses condition is now SATISFIED — `samples/sql_sample_v1/
> BDM_ACC_LOAN_INFO_Digitallending.sql` landed (562 lines) and parses
> with sqlglot mysql (verified: SET + 2 DML statements). The remaining
> gate before the Digitallending seed can be measured: the fixture owner
> must add the "dl" seed block — with the REQUIREMENT rows P15/P16/P18/P22
> of §8.5 — to `backend/tests/jaccard_canonical.py`; the block does not
> exist yet. This doc's line numbers/structure are reconciled against the
> final file; the served-form pins (§8.5) come from the probe against the
> final engine.

---

## 1. Script structure

```
L1-54   header comment block: title / 功能描述 (L2-4), 源表名 list (L6-27:
        ods_ccb_cb_loan_acctloan, ODS_HUB_SSALSFP, ods_ccb_ap_app_main_info,
        ods_ccb_cb_loan_acct, ods_ccb_ln_app_inf, ods_ccb_cb_loan_acctloandish,
        ods_ccb_cb_loan_acctloanpmt, ODS_CUPD_CLD_ACCTMASTER_NEW,
        ods_ccb_ln_loan_inf, ODS_CCB_LN_ORDER_INF, ods_ccb_cb_loan_acctbal,
        ods_ccb_cb_loan_acctloantermhist, ods_ccb_ln_app_inf_basic,
        ods_ccb_ln_account_inf, BDM_CUS_ICUSTOMER, BDM_ACC_DEPOSIT_ACCT,
        bdm_cus_ccustoner, bdm_cus_jointcustomer, bdm_fin_lrr_key_base_info),
        创建者 minghua.qiu / 创建时间 20230524 (L30-31), 修改日志 changelog (L32-52)
L55     SET odps.sql.decimal.odps2 = true;          (stripped by _clean_sql;
L56     blank                                         the 2 DML statements
                                                      are TOP0/TOP1)
L57-545 stmt1:  WITH temp_kmbh_gl (L58-77,
                 close `),` at L77),
                 temp_kmbh_ie (L78-97)
                 INSERT OVERWRITE TABLE bdm_acc_loan_info
                 PARTITION(data_dt='$(load_date)',                 (L99)
                           CHARGE_DEPARTMENT='WPB_CDT_Digitallending')
                 SELECT ... ~330 columns                            (L100-425)
                 FROM ods_ccb_cb_loan_acctloan A                   (L426)
                 22 LEFT JOINs (L427-543 — 19 active, 3 commented:
                                L450-453/L493-500/L501-503)
                 WHERE A.P_DT='$(load_date)'                        (L544)
                 ;                                                 (L545)
L546-547 blank
L548    comment (-- 操作日志记录)
L549-562 stmt2:  INSERT INTO TABLE rrcdm_job_log_exec_par(9 cols)  (L549)
                 SELECT '$(load_date)' AS data_dt, ...              (L550-558)
                 FROM bdm_acc_loan_info                             (L559)
                 WHERE data_dt='$(load_date)'                       (L560)
                   AND charge_department='WPB_CDT_Digitallending'   (L561)
                 ;                                                 (L562)
```

Global extraction facts: [PROBE: vars / deps / ALIAS edges — recorded from
the probe run; the script parses as 2 statements after the SET strip].

---

## 2. Table-level flow

```
ods_ccb_cb_loan_acctloan ─────────► bdm_acc_loan_info   (stmt1 INSERT OVERWRITE L99)
  read L426 (FROM, alias A), WHERE A.P_DT (L544)
ods_ccb_ap_app_main_info ─────────► bdm_acc_loan_info   (LEFT JOIN B, L427)
ods_ccb_cb_loan_acct ─────────────► bdm_acc_loan_info   (LEFT JOIN C, L430)
ods_ccb_ln_app_inf ───────────────► bdm_acc_loan_info   (LEFT JOIN D, L433)
ods_ccb_cb_loan_acctloandish ─────► bdm_acc_loan_info   (LEFT JOIN E, L436)
ods_ccb_cb_loan_acctloanpmt ──────► bdm_acc_loan_info   (derived F L439-443, ON L443)
ods_ccb_ln_loan_inf ──────────────► bdm_acc_loan_info   (LEFT JOIN G, L444)
ods_ccb_ln_order_inf ─────────────► bdm_acc_loan_info   (LEFT JOIN H, L447)
ods_ccb_cb_loan_acctbal ──────────► bdm_acc_loan_info   (derived J L454-464, ON L464)
ods_ccb_cb_loan_acctloantermhist ─► bdm_acc_loan_info   (derived K L465-470, ON L470)
ods_ccb_cb_loan_acctloantermhist ─► bdm_acc_loan_info   (derived L L471-476, ON L476)
ods_ccb_ln_app_inf_basic ─────────► bdm_acc_loan_info   (LEFT JOIN M, L477)
ods_ccb_ln_account_inf ───────────► bdm_acc_loan_info   (LEFT JOIN N, L480)
temp_kmbh_gl (CTE1, L58-77) ──────► bdm_acc_loan_info   (LEFT JOIN km_gl, L483)
temp_kmbh_ie (CTE2, L78-97) ──────► bdm_acc_loan_info   (LEFT JOIN km_ie, L485)
ODS_CUPD_CLD_ACCTMASTER_NEW ──────► bdm_acc_loan_info   (LEFT JOIN p1, L487)
ODS_CUPD_CLD_ACCTMASTER_NEW ──────► bdm_acc_loan_info   (LEFT JOIN p2, L491 — yesterday:
                                                          p2.P_DT = date_add('$(load_date)',-1);
                                                          file: date_add('$(load_date)',
                                                          INTERVAL -1 DAY) — parse-fix, dev. (c))
bdm_fin_lrr_key_base_info ─────────► bdm_acc_loan_info   (derived p3 L504-535, ON L534)
BDM_CUS_ICUSTOMER ─────────────────► bdm_acc_loan_info   (LEFT JOIN p4, L537)
BDM_ACC_DEPOSIT_ACCT ──────────────► bdm_acc_loan_info   (LEFT JOIN dsf_tm, L541)

CTE internals (feed temp_kmbh_gl / temp_kmbh_ie):
ODS_CUPD_CLD_ACCTMASTER_NEW (p1) ──► temp_kmbh_gl (L65), temp_kmbh_ie (L85)
ODS_HUB_SSALSFP (SSALSFP) ─────────► temp_kmbh_gl (L66), temp_kmbh_ie (L86)
  (joined on SSALSFP.ALGTCD/ALGMAB/ALACB/ALACS/ALACX = SUBSTR(p1.MXKMBH,…),
   ALSSCD='GL', SSALSFP.P_DT <= '$(load_date)'; WHERE p1.P_DT='$(load_date)')

Nested subquery sources (inside p3's exists-subquery / DM_FLAG2; the
DM_FLAG1/DM_FLAG2 names are confirmed by the file's L45 changelog comment
-- the OCR reads "OM_FLAG", the file and comment say DM_FLAG):
ODS_CDP_GDC_TABLE_COA_LIST (c1) ───► p3 (L520 — COA-list filter)
BDM_ACC_INTERNAL_COUNTERPARTY ─────► stmt1 SELECT (L407 — DM_FLAG2 exists-subq)
ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS (b) ─► stmt1 SELECT (L412-415 — DM_FLAG2)
v_bdm_customer_all('$(load_date)') (view call, a) ─► stmt1 SELECT (L408/L409)

COMMENTED OUT (NOT in flow):
ods_ccb_cb_loan_acctloantermhist (I)   L450-453  (join — replaced by K/L)
ODS_CCB_REPAY_LOAN_ACCOUNT_DELTA (T)   L493-500  (derived P2 join — replaced by p2)
bdm_pub_hsbc_acct_branch (t_branch)    L501-503  (join; the L106 column
  t_branch.org_no is also commented out in the SOURCE — the active ORG_NO
  is the literal 'CNHSBC900' at L107; NOTE the landed file has L106 ACTIVE
  — reconstruction deviation (a))

bdm_acc_loan_info ───────────────► rrcdm_job_log_exec_par  (stmt2 INSERT INTO L549, job log)
  read L559 (bare) → INSERT L549
```

---

## 3. Alias def-line map (I1 semantics — first token of the defining clause)

```
CTE temp_kmbh_gl (L58-77):
  p1       = ODS_CUPD_CLD_ACCTMASTER_NEW (L65)
  SSALSFP  = ODS_HUB_SSALSFP             (L66)
  t        = derived over p1 LEFT JOIN SSALSFP (L61-76)

CTE temp_kmbh_ie (L78-97):
  p1       = ODS_CUPD_CLD_ACCTMASTER_NEW (L85)
  SSALSFP  = ODS_HUB_SSALSFP             (L86)
  t        = derived                       (L81-96, mirror of CTE1)

stmt1 main SELECT (L100-545):
  A     = ods_ccb_cb_loan_acctloan         (L426, FROM)
  B     = ods_ccb_ap_app_main_info         (L427)
  C     = ods_ccb_cb_loan_acct             (L430)
  D     = ods_ccb_ln_app_inf               (L433)
  E     = ods_ccb_cb_loan_acctloandish     (L436)
  F     = derived over ods_ccb_cb_loan_acctloanpmt F1 (L439-442; F1 FROM L440)
  G     = ods_ccb_ln_loan_inf              (L444)
  H     = ods_ccb_ln_order_inf             (L447)
  I     = ods_ccb_cb_loan_acctloantermhist (L450-453 — COMMENTED OUT)
  J     = derived over ods_ccb_cb_loan_acctbal x (L454-463; x FROM L461)
  K     = derived over ods_ccb_cb_loan_acctloantermhist K1 (L465-469; K1 FROM L466)
  L     = derived over ods_ccb_cb_loan_acctloantermhist L1 (L471-475; L1 FROM L472)
  M     = ods_ccb_ln_app_inf_basic         (L477)
  N     = ods_ccb_ln_account_inf           (L480)
  km_gl = temp_kmbh_gl (CTE1)              (L483)
  km_ie = temp_kmbh_ie (CTE2)              (L485)
  p1    = ODS_CUPD_CLD_ACCTMASTER_NEW      (L487)
  p2    = ODS_CUPD_CLD_ACCTMASTER_NEW      (L491 — yesterday; read L164-165
                                          LOAN_ORI_MATURITY_DT compares p1/p2)
  P2    = derived over ODS_CCB_REPAY_LOAN_ACCOUNT_DELTA T (L493-500 — COMMENTED OUT)
  t_branch = bdm_pub_hsbc_acct_branch      (L501-503 — COMMENTED OUT)
  p3    = derived over bdm_fin_lrr_key_base_info bi (L504-535; bi FROM L516;
          inner km derived L507-532; ROW_NUMBER OVER (PARTITION BY
          arrangement_local_number ORDER BY SUBSTR(cb_pointer,2,5) DESC) rn;
          exists-subquery on ODS_CDP_GDC_TABLE_COA_LIST c1 L519-524)
  p4    = BDM_CUS_ICUSTOMER                (L537)
  dsf_tm= BDM_ACC_DEPOSIT_ACCT             (L541)

subquery aliases (nested):
  a     = v_bdm_customer_all('$(load_date)')  (L408, L409 — view call)
  b     = ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS (L412)
  c1    = ODS_CDP_GDC_TABLE_COA_LIST          (L520)
```

---

## 4. Field ground truth — bdm_acc_loan_info.data_dt

### 4.1 Occurrence lines (the "touch points")

```
L99   PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT='WPB_CDT_Digitallending')
                                           write, stmt1 target partition
L550  '$(load_date)' AS data_dt            write, stmt2 output column (literal)
L560  data_dt = '$(load_date)'             read, stmt2 WHERE, bare → bdm_acc_loan_info (L559)
L561  charge_department = 'WPB_CDT_Digitallending'
                                           read, stmt2 WHERE (charge dept, not data_dt)
```

Instance identity: the field is NOT read anywhere inside stmt1 — its only
stmt1 occurrence is the partition write (L99). This script has no
own-scope-alias READ instances (the SUP script's L18/L43/L158 class) and no
self-join of the target (the SUP script's p2@199 class): the data_dt
closure is entirely stmt1-write + stmt2-read.

NOT this field (belongs to other tables — negative proof):

```
L73   SSALSFP.P_DT <= '$(load_date)'   → ODS_HUB_SSALSFP (SSALSFP, CTE1)
L74   p1.P_DT = '$(load_date)'         → ODS_CUPD_CLD_ACCTMASTER_NEW (p1, CTE1)
L93   SSALSFP.P_DT <= '$(load_date)'   → ODS_HUB_SSALSFP (SSALSFP, CTE2)
L94   p1.P_DT = '$(load_date)'         → ODS_CUPD_CLD_ACCTMASTER_NEW (p1, CTE2)
L429  B.P_DT                           → ods_ccb_ap_app_main_info (B)
L432  C.P_DT                           → ods_ccb_cb_loan_acct (C)
L435  D.P_DT                           → ods_ccb_ln_app_inf (D)
L438  E.P_DT                           → ods_ccb_cb_loan_acctloandish (E)
L441  F1.P_DT                          → ods_ccb_cb_loan_acctloanpmt (F1)
L446  G.P_DT                           → ods_ccb_ln_loan_inf (G)
L449  H.P_DT                           → ods_ccb_ln_order_inf (H)
L453  I.P_DT                           → ods_ccb_cb_loan_acctloantermhist (I — commented join)
L462  x.P_DT                           → ods_ccb_cb_loan_acctbal (x)
L479  M.P_DT                           → ods_ccb_ln_app_inf_basic (M)
L482  N.P_DT                           → ods_ccb_ln_account_inf (N)
L489  p1.P_DT                          → ODS_CUPD_CLD_ACCTMASTER_NEW (p1)
L491  p2.P_DT = date_add('$(load_date)',-1) → ODS_CUPD_CLD_ACCTMASTER_NEW (p2 — yesterday)
L503  t_branch.data_dt                 → bdm_pub_hsbc_acct_branch (t_branch — commented join)
L518  data_dt = '$(load_date)'         → bdm_fin_lrr_key_base_info (bi) — p3's inner WHERE
L521  c1.p_dt (subquery)               → ODS_CDP_GDC_TABLE_COA_LIST (c1)
L539  p4.data_dt                       → BDM_CUS_ICUSTOMER (p4)
L543  dsf_tm.data_dt                   → BDM_ACC_DEPOSIT_ACCT (dsf_tm)
L544  A.P_DT = '$(load_date)'          → ods_ccb_cb_loan_acctloan (A) — stmt1 main WHERE
L407  BDM_ACC_INTERNAL_COUNTERPARTY.data_dt → internal-counterparty subquery (DM_FLAG2)
L413  b.p_dt                           → ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS (b) — DM_FLAG2
L373  '$(load_date)' AS dis_data_date  → literal output column (not data_dt)
```

### 4.2 Downstream layer-by-layer (targets of targets) — REQUIREMENT

```
LAYER 0 — the field (3 occurrences):  L99 (partition write), L550
          (stmt2 output column), L560 (stmt2 WHERE read)

LAYER 1 — direct targets:
  L99  ──► bdm_acc_loan_info (L99)     ← the partition write lands here
  L550 ──► rrcdm_job_log_exec_par (L549)  ← the output column feeds stmt2's INSERT
  L560 ──► bdm_acc_loan_info (L559)    ← the stmt2 WHERE read constrains the job-log input

LAYER 2 — targets of layer 1 (REQUIREMENT — the cross-statement chain):
  bdm_acc_loan_info ─► rrcdm_job_log_exec_par   (read L560 → INSERT L549)

LAYER 3 — final targets (sinks):
  bdm_acc_loan_info    (stmt1 target partition)
  rrcdm_job_log_exec_par   (stmt2 job log)
```

Semantic closure: **8 nodes** (data_dt@99 + data_dt@550 + data_dt@560 +
bdm_acc_loan_info@99 + bdm_acc_loan_info@559 + rrcdm_job_log_exec_par@549 +
⟐output1@0 + ⟐output2@0), **2 final sinks** — mirror of the SUP doc's
closure shape: the stmt1 INSERT target and the stmt2 job-log sink. NOTE:
the stmt1 SOURCE tables (the 20 FROM/JOIN tables of §2) are NOT in the
data_dt closure — the field is never read in stmt1 (its only stmt1
occurrence is the partition write); every source's load-date filter is its
own P_DT/data_dt (negative proof §4.1). Requirement semantics:
one-source→targets flow, no dead-ends, no-bypass cross-statement.

### 4.3 Edge inventory — what the graph must have (REQUIREMENT, mirrors SUP §4.3 items 3/4)

The SUP seed's requirement rows map 1:1 onto this script — the two
statements have the same shape (INSERT OVERWRITE target + INSERT INTO job
log), so the requirement edges are the same two "MISSING" classes, here
stated as MUST-HAVE:

```
3. ⟐output1 → bdm_acc_loan_info@99   table-level write leg (stmt1's output VT
   feeds its INSERT target — the write leg; the benchmark asserts it as
   TABLE_FLOW stamped flow_kind='write', R19.3)
4. bdm_acc_loan_info@99 → bdm_acc_loan_info@559  cross-statement
   write→read link (stmt2 reads the stmt1 target; the R19.3 no-bypass
   chain must route THROUGH the reader instance at L559:
   output1 → bdm → [stmt2 read] → output2 → rrcdm)
```

NOT APPLICABLE here — the SUP doc's MISSING items 1/2 (own-scope-alias
READ edges `p1.data_dt@43 → bdm@29`, `p1.data_dt@158 → bdm@84`): this
script has NO `data_dt` read inside stmt1 (the field appears only at the
partition write L99; stmt1's WHERE is A.P_DT at L544, the CTE WHEREs are
p1.P_DT at L74/L94 — all other tables' fields, negative proof §4.1).

These are REQUIREMENT rows (the doc's ideal — what the graph must show),
never a description of the current engine output. The benchmark pins them
(jaccard_canonical.py Digitallending block, rows P15/P18/P22/P16 — §8.5)
and the R19.3 chain checks assert the no-bypass property.

[PROBE: the served L2's realization of each requirement row — edge ids,
types, hl lines, flow_kind — recorded in §8.5.]

---

## 5. Highlight ground truth

> **⚠️ SUPERSEDED (2026-08-10, user ruling):** §5-style field-occurrence
> highlight lists are superseded by the formal definition in §8 —
> Highlight is per-edge (edge = one data flow), there is no field
> highlight. Kept here only for the audit trail.

### 5.1 The field's own lines (candidates for §8.3.2 fallback only)

```
L99   PARTITION(data_dt='$(load_date)', ...)    ← partition write (stmt1 target)
L550  '$(load_date)' AS data_dt                 ← stmt2 output column
L560  data_dt = '$(load_date)'                  ← stmt2 WHERE read
```

### 5.2 Negative proof — lines correctly NOT highlighted

```
L73/93  SSALSFP.P_DT   → ODS_HUB_SSALSFP (other table)
L74/94  p1.P_DT        → ODS_CUPD_CLD_ACCTMASTER_NEW (other table)
L429-544 (B/C/D/E/F1/G/H/I/x/M/N/p1/p2/A).P_DT → their own tables (other tables)
L503    t_branch.data_dt → bdm_pub_hsbc_acct_branch (commented join)
L518    data_dt        → bdm_fin_lrr_key_base_info (other table)
L539    p4.data_dt     → BDM_CUS_ICUSTOMER (other table)
L543    dsf_tm.data_dt → BDM_ACC_DEPOSIT_ACCT (other table)
L373    '$(load_date)' AS dis_data_date → literal output column (other field)
```

### 5.3 Highlight semantics

- The tool highlights **edge anchor lines** only (§8), never the table
  FROM lines — correct by design.
- Literal producers (`'$(load_date)'`) are not traced — by design.

---

## 6. Test contract (what a regression test must pin)

```
1. parse_errors == [] ; the script parses with sqlglot mysql
2. alias def lines: the §3 map (verified lines — reconciled with the
   landed file 2026-08-12, §RECONCILIATION)
3. bdm_acc_loan_info.data_dt closure (L2): [PROBE] nodes / [PROBE] edges
4. THE GROUND TRUTH: the requirement closure — the two sinks
   (bdm_acc_loan_info, rrcdm_job_log_exec_par), the stmt1 write leg
   (output1 → bdm@99) and the cross-statement write→read chain
   (bdm@99 → bdm@559 → output2 → rrcdm@549), §4.3
5. highlights: the §8.5 closure anchors (probe-pinned)
```

Status: analysis only — no source changes.

---

# PART II — CANONICAL GROUND TRUTH v2 (benchmark spec, Digitallending round 2026-08-12)

This part is the machine-comparable target. The benchmark
(`backend/tests/test_jaccard_benchmark.py`) compares the system's live L2
output against THIS spec (via `backend/tests/jaccard_canonical.py`) and
reports the recall/precision pair per seed per feature (J12-12: A = B ⟺
recall = precision = 1.0 — genuine SET EQUALITY, never a size check). B is
compiled from the REQUIREMENT sections (§4.2/§4.3), J12-13 — never from
the engine's emitted form; the §8.5 closure table records the served
realization of each requirement row (probe-pinned, after the requirements
were written).

## 7.1 The trials (mirror of the SUP doc — what each calculation proved)

[PROBE: the same three-trial structure — filtered-L2 closure, downstream
BFS, source_tables-driven closure — with this script's numbers.]

## 7.2 THE canonical spec (the benchmark target)

**Nodes (canonical names @ lines):**

```
field (3):        data_dt@99, data_dt@550, data_dt@560
table/scope (3):  bdm_acc_loan_info@99 (stmt1 target),
                  bdm_acc_loan_info@559 (stmt2 reader),
                  rrcdm_job_log_exec_par@549
VT plumbing (2):  ⟐ output1@0, ⟐ output2@0
```

**Sinks (2):** `bdm_acc_loan_info@99`, `rrcdm_job_log_exec_par@549`.

The stmt1 source/join tables (§2) are NOT canonical nodes of the data_dt
closure — the field is only written at the partition (L99) and never read
in stmt1 (the sources' load-date filters are their own P_DT/data_dt,
negative proof §4.1; no P1 seed copies land on them).

**Edges (canonical endpoint pairs — REQUIREMENT, §4.2/§4.3):** the stmt1
write leg (⟐output1 → bdm@99), the stmt2 read (data_dt@560 → bdm@559), the
reader's read leg (bdm@559 → ⟐output2), the stmt2 write leg (⟐output2 →
rrcdm@549), plus the value writes (data_dt@99 → ⟐output1, data_dt@550 →
⟐output2) and the SCHEMA / FILTER-companion rows pinned in §8.5.
[PROBE: full list.]

**Highlights:** per §8 — every closure edge anchors at exactly one line.

## 7.3 Benchmark protocol (the loop)

1. Run `docker exec -w /app/backend gps-sql-backend python3 -m pytest
   tests/test_jaccard_benchmark.py -q` → per-seed recall/precision +
   the improvement backlog (unmatched canonical rows).
2. Classify each diff line: (a) engine defect → fix the engine (build on
   extraction-time info — never patch solutions); (b) ground-truth wrong
   → repair THIS doc + fixture with evidence (which probe proved it, why
   the old entry was wrong); (c) fixture typo → fix the fixture.
3. Re-run. Repeat until nothing is left to improve (matched rows == all
   canonical rows, every canonical node realized, A_highlights ==
   B_highlights), then ratchet FLOORS with measured values.
4. The benchmark is the regression gate: bdm/sup floors must never
   regress; the Digitallending seed's floors ratchet up from the measured
   values (the seed is NOT measured until the WAIT-CONDITION NOTE is
   satisfied).

## 7.4 Loop round 1 outcome

[PROBE: this script's convergence record — filled during the iteration
round.]

---

## 8. Highlight — formal definition (v3.3.147, user ruling 2026-08-10)

> This section is the AUTHORITATIVE definition of the highlight feature
> (mirror of the SUP doc §8 — every L2 edge highlights, anchor rules
> 1-7). For this script the canonical anchors are the probe-pinned §8.5
> rows.

### 8.1 Feature definition

Per §8.1 of the SUP doc: every L2 edge carries exactly one
`highlight_line` (the flow's anchor line per §8.3) — never a range.

### 8.2 What is NOT part of the feature

There is no field highlight (SUP §8.2).

### 8.3 Edge-highlight contract (per edge e — anchor rules, in priority order)

Identical rule set to the SUP doc §8.3 (field flow / READ / write group /
synthetic-source / chain / SCHEMA / SUBSET rules 1-7). The Digitallending
rows in §8.5 record the rule each row follows.

### 8.4 Counting invariant

Per edge: exactly one primary line; every closure edge is pinned (§8.5)
so the payload count is deterministic.

### 8.5 Highlight ground truth for testing (CANONICAL_EDGE_LINES — complete)

**The complete table — [PROBE: N] entries, this sample, post-promotion
state (the Digitallending block of jaccard_canonical.py; REQUIREMENT rows
P15/P16/P18/P22 marked; each row's Real type = the served realization,
probe-pinned — the PENDING-PROBE placeholder convention of the pl doc):
**

| # | Pair | Kind | Real type (post-promotion) | Seed | Anchor |
|---|------|------|---------------------------|------|--------|
| P15 | `⟐output@0 → bdm@99` — REQUIREMENT row (§4.3 item 3 — the stmt1 write leg) | write | TABLE_FLOW (flow_kind='write', *_dml_out) | dl | 99 |
| P16 | `⟐output@0 → rrcdm@549` — REQUIREMENT row (§4.2 LAYER-2 — the stmt2 write leg) | write | TABLE_FLOW (flow_kind='write', *_dml_out) | dl | 549 |
| P18 | `data_dt@560 → bdm@559` — REQUIREMENT row (§4.2 — the stmt2 read) | READ | REF (promoted) | dl | 559 |
| P22 | `bdm@559 → ⟐output@0` — REQUIREMENT row (§4.2 — the reader's read leg) | chain | TABLE_FLOW | dl | 559 |
| [PROBE] | `data_dt@99 → ⟐output@0` — the stmt1 value write (mirror of SUP row 12/X2) | value | TABLE_FLOW (value-write) | dl | 99 |
| [PROBE] | `data_dt@550 → ⟐output@0` — the stmt2 value write (mirror of SUP row 17/X4) | value | TABLE_FLOW (value-write) | dl | 550 |
| [PROBE] | `data_dt@560 → bdm@560` — the stmt2 WHERE FILTER companion (mirror of SUP X5/row 23) | field flow | FILTER (promoted) | dl | 560 |
| [PROBE] | SCHEMA rows — ⟐output1 → data_dt@99, ⟐output2 → data_dt@550 (structure, rule 6) | structure | SCHEMA/TABLE_COLUMN | dl | 99/550 |
| [PROBE] | remaining rows — any served-form rows the probe finds beyond the pinned set (per the SUP convention: chain-completeness C-rows, extras) | | | dl | |

Closure seeds: **"dl = [PROBE] nodes / [PROBE] edges"** (probe-pinned —
the served L2 closure for the `bdm_acc_loan_info.data_dt` seed on this
script). [PROBE: the seed/block name the fixture uses — the doc assumes
"dl" (Digitallending) per the jaccard_canonical.py naming; the fixture
block does not exist yet.]

### 8.6 Current-system gaps this definition exposes

[PROBE: any served-form gaps found during the iteration round.]

### 8.7 Real edge types → flow kind → highlight contract (16-row mapping, 2026-08-10)

Identical to the SUP doc §8.7 — the 16-row mapping; this script's rows
are the §8.5 table.

### 8.8 L2 display of flow kind — design RULED (2026-08-10, user)

Identical to the SUP doc §8.8 — flow-kind labels on every edge, click →
SQL anchor highlight + reason panel.

### 8.9 Verification plan

Identical to the SUP doc §8.9 (INDIRECT / WINDOW / CORRELATED / SET_OP
verified on other samples — this script exercises none of them).

### 8.10 Open confirmations

Identical to the SUP doc §8.10 — nothing new for this script.
