# Flow-only view: the complete edge show/hide rules

> Every rule that decides whether an edge appears in the L2 flow-only view, with examples
> from the flagship scripts, and the confusing ones labeled. Written 2026-09-01 for the
> user's review; the two ⚡ ruling items were RESOLVED the same day (§7-A write leg only,
> §7-B the edge drops and the edge-less chip is pruned) — their §7 entries keep the history.
> Every trace row below is payload-checked (REV 15, 2026-09-02): against the regenerated
> flow-only baselines in `backend/tests/snapshots/` where the searched field is a snapshot
> seed, otherwise against a live in-process build of the same `_build_l2_graph` path
> (`PYTHONHASHSEED=0`), labeled "live build" on the row.
>
> **REV 9–15 (2026-09-02)** added rule 2h (provenance-linked AS-alias routing), rules 6d/6e
> (alias/feeder-box scope + own-segment classification) with the orphan-BOX prune, rule 4e
> (producer-occurrence anchoring, LANDED — commit `8c5c6a4`, v3.3.199), the flow-only-only UI
> (Full view CUT, R53), and the trace corrections (EAST5 × `BBZ` = 10 edges / 6 nodes).

## The foundation: two ways an edge earns its place

| # | An edge is shown if… | Example |
|---|---|---|
| **V** | **The searched field's VALUE travels on it** — the field is read, computed, or written | `p1.lending_ref` in a SELECT → written into `bdm_acc_loan_info_sup` |
| **S** | **It's structural skeleton** — it positions the boxes the value lives in (table/CTE/alias compounds, FROM/JOIN headers, belongs-to "field X exists here") | `FROM bdm_acc_loan_info p1` (the header edge) |

Everything below refines these two ideas.

---

## 1. SEED rules — where the closure starts

| # | Rule | Shown? | Example |
|---|---|---|---|
| 1a | Occurrences of the searched field on the searched table's compounds seed the closure | ✅ | Search `lending_ref` → the `p1.lending_ref` chips on `bdm_acc_loan_info` |
| 1b | #399 alias expansion: a TVF/alias/CTE whose projection carries the field also seeds | ✅ | `v_bdm_customer_all('...') a` — searching `a.cust_no` seeds through the TVF |
| 1c | Same-name occurrences on OTHER tables' compounds do **not** seed | ❌ | Searching `bdm_acc_loan_info.data_dt`: the `c/d/e.data_dt` chips of `bdm_pub_branch` / `BDM_ACC_INTERNAL_COUNTERPARTY` do not seed — **(RC-A class, fixed by the R-GATE)** |

---

## 2. VALUE rules — edges that carry the field's value

| # | Rule | Shown? | Example |
|---|---|---|---|
| 2a | **Reads**: a projection/expression reading the field's value | ✅ | `SELECT p1.lending_ref` @163 |
| 2b | **Writes**: the value written into a target table | ✅ | `INSERT OVERWRITE bdm_acc_loan_info_sup ... p1.lending_ref` |
| 2c | **Computes**: the value inside an expression feeding an output | ✅ | `CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` @82 — COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` (canonical LFS133). L41's `CONCAT(...) = p1.lending_ref` is a **full**-view-only anchor |
| 2d | **Filters on the field**: a predicate selecting rows by it | ✅ | `WHERE p1.data_dt = '$(load_date)'` |
| 2e | **Join keys on the field**: the join operand IS the field | ✅ | `ON p6.lending_ref = p1.lending_ref` @156 |
| 2f | **Group/window keys on the field**: it decides grouping/ranking | ✅ | `GROUP BY ... product` @246; `ROW_NUMBER() OVER(PARTITION BY p1.acnw)` @64 — the **Reappears** stage |
| 2g | A statement writes the SEARCHED field's column with a **literal/constant** value | ✅ (write leg only — USER RULING 2026-09-01, resolving 7-A) | The job-log: `INSERT INTO rrcdm_job_log_exec_par(data_dt, ...) SELECT '$(load_date)' AS data_dt, COUNT(1)...` — searching `data_dt`, its write leg shows (PL @253, EAST5 @179) even though the value is a constant; the INSERT's other literal columns stay out |
| 2h | A searched SOURCE field's value is written to the target **under an AS-alias** (provenance-linked routing) | ✅ **(USER CONFIRMED 2026-09-02)** | EAST5 L50 `REPLACE(a.entd_paym_dt,"_","") As stzfrq` — the alias's ⟐output legs @50 stay served, so the value chain reaches the DML without a hole. Proof of admission: the closure already serves the `field → alias` TRANSFORM (provenance), the frame is the write target's own column, and the statement writes no searched-field column itself (the 7-A boundary). Guard: a SIBLING's alias legs stay dropped (`reserved_field8`) |

---

## 3. SIBLING rules — other fields written by the same statement

*2026-09-02: the Full view is cut from the requirement (source kept in the repo) (flow-only is the product view; user ruling —
`requirements_v2.md` §"Amendment (2026-09-02)", traceability R53). The "full view" statements below
describe the cut view's semantics and the payload contract, both kept unchanged in the
codebase. The Full view's source code and this document's full-view rules are KEPT — nothing is
removed from the git repository; only the UI entry point is closed (the L2 renders the flow-only
view exclusively).*

| # | Rule | Shown? | Example |
|---|---|---|---|
| 3a | A sibling field's **belongs-to** edge (structural fact: it exists on this line) | ❌ **(USER RULING 2026-09-01 — reversed, was ✅)** | `reserved_field8` written at L82 next to `lending_ref` — its belongs-to edge is **dropped** (mess, no data-flow contribution). The searched field's own belongs-to / Reappears edges are untouched — only a *sibling's* belongs-to drops. **CONFIRMED same day:** also remove the sibling chips this leaves floating edge-less — "If the sibling chips, which is not [the] searched target field, and doesn't have any edge, they are not contributing to the data flow. I think they should be removed." (USER RULING 2026-09-01, `_prune_orphan_sibling_chips`) |
| 3b | A sibling field's **value legs** (its write/read/compute edges) | ❌ | Searching `lending_ref`: `reserved_field8`'s write leg, read leg, and output-membership edges are dropped — **(the field-involvement rule, user-ruling #48; fixed 4 over-included edges)** |
| 3c | The sibling field's **chip** in the closure | ❌ once edge-less (CONFIRMED) | A sibling chip survives while ANY kept edge touches it — e.g. `reserved_field8` stays because the seed's own L82 COMPUTED feeds it. A chip whose last edge was its belongs-to is **removed with it** (the confirmed 2026-09-01 ruling) — "this column exists on this box" is a **full-view** fact |

### 3a in full — three complete worked examples (post-ruling)

The line the rule now draws (**USER RULING 2026-09-01, full variant
confirmed**): NOTHING of a sibling field anchors it in the searched
field's closure — not its value legs (3b), not its belongs-to, and not
its chip once the chip is edge-less. The user: "If the sibling chips,
which is not [the] searched target field, and doesn't have any edge,
they are not contributing to the data flow. I think they should be
removed." A sibling chip survives ONLY while a kept edge of the searched
field's own flow still touches it. The three co-occurrence shapes,
re-told as **traces**: the searched field first, then one row per SQL
line, each row carrying the edges the engine actually serves there
(checked line by line against the regenerated flow-only baselines in
`backend/tests/snapshots/`).

**Example 1 — co-written CASE sibling (SUP_M × `lending_ref`)**

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — canonical LFS133) (edge: SCHEMA/structure @82, `p6@155` → `lending_ref@82` — canonical LFS134)
- L82 (the same line, sibling `reserved_field8`): (dropped — USER RULING 2026-09-01: the sibling belongs-to SCHEMA/structure `loan_final@64` → `reserved_field8@82` the **full** view still serves here — canonical LFS135 REMOVED) (dropped — field-involvement rule 3b: the CASE value legs, the ⟐output membership and the L183 write-projection read leg, which the **full** view carries as SCHEMA/structure @183 ×3, `p1@29/@84/@198` → `reserved_field8@82`, plus `bdm_acc_loan_info_sup@160` → `reserved_field8@183` and `output@160` → `reserved_field8@82`)

The cited lines in their SQL (the alias instances and the write target the dropped edges cite, verbatim):

```sql
L29:               bdm_acc_loan_info p1   ← `p1@29` — the CTE's own p1 instance
L64:       ,loan_final AS (   ← `loan_final@64` — the CTE the JOIN target box comes from
L84:           bdm_acc_loan_info p1   ← `p1@84` — the CTE instance L163 projects
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155` — the searched field's own source box
L156:          ON p6.lending_ref = p1.lending_ref
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `bdm_acc_loan_info_sup@160` / `output@160` — the write target and its output frame
L163:        ,p1.lending_ref -- 借据编号   ← `lending_ref@163` — the write projection beside the sibling
L183:        ,p1.reserved_field8 AS reserved_field8 -- rollover业务标识（修改到期日期）   ← `@183` — the sibling's write-projection read leg
L198:        loan_final p1   ← `p1@198` — the outer query's p1 instance
```

*Note:* the `reserved_field8` **chip itself** survives — the seed's own COMPUTED edge feeds it at L82 (the CASE that computes `reserved_field8` READS `lending_ref`), so the confirmed prune keeps it: it is edge-anchored by the searched field's own flow, not by its belongs-to. The rest of this closure (L9/13/16/19/22/26/29/50/52/59/64/67/82/84/95/117/150/155/156/160/163/198/199/201, 51 edges) is untouched — only the sibling's own rows went.

Read the picture as: "`reserved_field8` appears because YOUR value flows
into it" — never "…and it also exists on this box" (that fact is a
full-view fact now).

**Example 2 — co-filter sibling (PL × `data_dt`)**

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L263: `FROM bdm_acc_loan_info` — (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`; canonical F1)
- L265: `AND charge_department = 'OPS_CLBS_PLoan';` — (dropped — USER RULING 2026-09-01: no edge served here and the edge-less `charge_department@265` chip pruned with it — canonical point 26: the J12-20 doc row is repaired out of `CANONICAL_NODES`)

The cited lines in their SQL (the two endpoint boxes the edges cite, verbatim):

```sql
L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19` — the searched table's own box
L253:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,…,STATUS,remarks)   ← `output@253` — the job-log statement's output frame
```

*Note:* the searched field's own predicate @264 is untouched (2d). This is the row J12-20 pinned and the **resolved** §7-B — resolved then by ADDING the chip; the belongs-to that anchored it is now dropped, and the edge-less chip removed, by this ruling. (The old text wrote the predicate as `p1.data_dt` — the sample line has no `p1.` prefix.)

**Example 3 — dynamic-partition co-write (EAST5 × `p_dt`)**

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (dropped — USER RULING 2026-09-01: the sibling `CHARGE_DEPARTMENT@41` belongs-to edges the **full** view serves here — `east5_stzfxxb@41` → `CHARGE_DEPARTMENT@41` and `output@41` → `CHARGE_DEPARTMENT@41` ×2)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — field-involvement rule 3b: the feeding expression, and the sibling belongs-to SCHEMA/structure @51 `a@141` → `charge_department@51` the **full** view carries)

The cited lines in their SQL (the sibling's owner box, verbatim):

```sql
L141:      FROM bdm_acc_entrusted_payment a --受托支付信息表   ← `a@141` — the sibling's owner box `bdm_acc_entrusted_payment`
```

*Note:* L41 is `p_dt`'s own write (a literal partition value — rule 2g); the same PARTITION clause co-writes `charge_department` as a DYNAMIC partition. This is the shape that motivated the ruling: write-heavy statements co-write dozens of columns, and under the old rule every one of them dragged a chip + belongs-to edge into the closure.

**One-sentence summary for all three**: the searched field's closure
shows only what the searched field's own value drives — a sibling has no
edges and no edge-less chips in it. "What else is written on this line /
this box" is a question for the full view.

### Worked examples — the other rule groups

Three complete cases per group, same convention as §3a: the searched
field first, then one row per SQL line with the edges the engine
actually serves there (payload-checked against
`backend/tests/snapshots/` where the searched field is a snapshot seed,
against a live in-process build of the same `_build_l2_graph` path —
`PYTHONHASHSEED=0`, stable across runs — and labeled "live build"
where it is not), shown (✅) vs dropped (❌).

**§1 SEEDS — where the closure starts**

1. *1a, own-table occurrence*: search `lending_ref` → every `p1.lending_ref`
   chip on the `bdm_acc_loan_info` compounds seeds. ✅
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L13: `lending_ref` — ✅ (edge: SCHEMA/structure @13, `rollover_loan_info@9` → `lending_ref@13`) (edge: REF/value copy @13, `lending_ref@13` → `lending_ref@82`)

    The cited lines in their SQL (the CTE head and the lit read, verbatim):

        L9:        WITH rollover_loan_info AS (   ← `rollover_loan_info@9` — the CTE box the seed belongs to
        L12:         SELECT
        L13:           lending_ref   ← the seed chip's own line
        L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← `lending_ref@82` — the NVL read the value copy lights

   *Note:* the seed's own occurrences are the closure's first lit lines; L82's NVL read is lit by the same value copy.

2. *1b, alias expansion (#399)*: `FROM v_bdm_customer_all('...') a`,
   search the TVF's `cust_no` → the alias's owning entities seed. ✅
    - Search field: `ods_gdc_split_fg_rating_temp.cust_no` — the snapshot seed, whose closure carries the TVF-alias form `a.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
    - L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: TABLE_FLOW/chain (read into output) @1103, `a@1103` → `output(exists13)@1103`) (edge: TABLE_FLOW/chain (VT chain) @1103, `output(exists13)@1103` → `output@867`) (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`) (edge: REF/read @1103, `cust_no@1105` → `a@1103`)
    - L1104: `LEFT JOIN bdm_acc_deposit_acct b` — ✅ (edge: ALIAS/chain (alias hop) @1104, `bdm_acc_deposit_acct@1104` → `b@1104`) (edge: REF/read @1104, `cust_no@1105` → `b@1104`)
    - L1105: `ON a.cust_no = b.cust_no` — ✅ (edge: JOIN/join step @1105, `cust_no@1105` → `output(exists13)@1103` — served twice, one per side of the predicate) (edge: SCHEMA/structure @1105, `a@1103` / `b@1104` / `b@1111` → `cust_no@1105` ×3) (edge: COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`)

    The cited lines in their SQL (the TVF chain and the far endpoints, verbatim):

        L867:      INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}',CHARGE_DEPARTMENT='GTRF_RFN')   ← `output@867` — the statement the EXISTS chain feeds
        L1103:       WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a   ← `a@1103` / `v_bdm_customer_all@1103` — the TVF and its alias
        L1104:         LEFT JOIN bdm_acc_deposit_acct b   ← `b@1104`
        L1105:         ON a.cust_no = b.cust_no   ← the cited ON line
        L1110:         SELECT 1
        L1111:           FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS b   ← `b@1111` — the third alias instance
        L1119:       END AS DM_FLAG2  -- 境内外标识"F"境外/"I"境内   ← `DM_FLAG2@1119` — the compute step's target chip

   *Note:* the TVF's projection carries the field, so the alias's owning entities seed — the TVF box `v_bdm_customer_all@1103` and the alias `a@1103` are both in the served closure.

3. *1c, cross-table same-name (RC-A)*: search `bdm_acc_loan_info.data_dt`
   → the `c.data_dt` / `D.DATA_DT` / `T_BRANCH.data_dt` chips of
   `BDM_PUB_BRANCH` / `BDM_PUB_HSBC_ACCT_BRANCH` are same-NAME,
   different-TABLE — they do NOT seed. ❌ Their closures stay dark.
    - Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
    - L223: `LEFT JOIN BDM_PUB_BRANCH D ON SUBSTR(A.HKZH,1,9) = D.org_no AND D.DATA_DT = '${load_date}'` — ❌ (no edge served @223 in this closure — `D.DATA_DT` is another table's same-named column, the R-GATE class)
    - L236: `AND data_dt='${load_date}'` — ❌ (no edge served @236 — that occurrence belongs to `bdm_fin_lrr_key_base_info`, a different table)
    - L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250; the **full** view does carry the sibling chip's own SCHEMA/structure `T_BRANCH@250` → `data_dt@250`, which is exactly what the gate keeps out)
    - L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19` — the searched table's own occurrence)

    The cited lines in their SQL (the searched table's box and the clause L236 continues, verbatim):

        L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19` — the searched table's own box
        L235:      WHERE SUBSTR(glbl_source_chartfield,1,3)='ACR'   ← the WHERE clause L236's `AND data_dt=…` continues

   *Note:* this was the R-GATE's fix — same name, different table, no seed.

**§2 VALUE — edges that carry the field's value**

1. *2d, filter*: `WHERE data_dt = '${load_date}'` → the predicate edge on
   the searched compound shows; the highlight lands on the WHERE line.
    - Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
    - L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
    - L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`)

    The cited lines in their SQL (the two endpoint boxes, verbatim):

        L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19` — the searched table's own box
        L253:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,…,STATUS,remarks)   ← `output@253` — the job-log frame the read-into-output edge targets

   *Note:* the highlight lands on the WHERE line, not on the box.

2. *2e, join key*: `ON p6.lending_ref = p1.lending_ref` @156 → the JOIN
   edge shows at the join's own line (and ONLY there — a join edge
   anchored at a projection line is the Class-1 defect, dropped).
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
    - L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156, `lending_ref@13` → `loan_final@64` — the p1 side) (edge: JOIN/join step @156, `lending_ref@82` → `loan_final@64` — the p6 side, canonical LFS138) (edge: SCHEMA/structure @156, `bdm_acc_loan_info@16` → `lending_ref@13`) (edge: SCHEMA/structure @156, `rollover_loan_info@9` → `lending_ref@82`)
    - L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ❌ no JOIN edge here (a projection line; it serves the seed's own COMPUTED/compute step `lending_ref@82` → `reserved_field8@82` instead)

    The cited lines in their SQL (the two sides' occurrences and the JOIN target, verbatim):

        L9:        WITH rollover_loan_info AS (   ← `rollover_loan_info@9` — the p6-side box
        L13:           lending_ref   ← `lending_ref@13` — the p1-side occurrence
        L16:             bdm_acc_loan_info   ← `bdm_acc_loan_info@16` — the p1-side box
        L64:       ,loan_final AS (   ← `loan_final@64` — the JOIN target box

   *Note:* both sides of the predicate light at the join's own line — never at a projection line.

3. *2g, name-but-no-value*: the job-log `INSERT INTO rrcdm_job_log_exec_par(...) SELECT '$(load_date)' AS data_dt` writes a column NAMED like the field but the value is a literal — ✅ **resolved by ruling 7-A (write leg only, 2026-09-01)**: searching `data_dt`, its write edge shows (see §7-A).
    - Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
    - L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ ruling 7-A (write leg only, 2026-09-01): shown — (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253` — canonical P16)
    - L254: `SELECT '${load_date}' AS data_dt,` — ✅ ruling 7-A: shown — (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253` — canonical V2) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254` — canonical M1)

    context: complete in the rows above.

   *Note:* the engine serves this trunk here — and EAST5's (@179 write leg, with the read/filter legs @189/@190) — while SUP_M's identical job-log trunk (@211/@213) stays dark. That is no longer an inconsistency: ruling 7-A (resolved 2026-09-01, write leg only) shows the write leg for the column the log WRITES (`data_dt` @253/@254, `p_dt` @179) and gives a field the log does NOT write (`lending_ref`) nothing. EAST5's own @180 `data_dt@180` belongs-to is a **full**-view row the closure drops — it is a SIBLING there (the searched field is `p_dt`), whereas PL's @254 row is the searched field's own.

**§4 TWINS — the same field at many lines**

1. *4a, per-occurrence lines*: `charge_department`'s CASE arms light
   exactly at {54, 55, 56, 66, 68, 70} — each occurrence at its own line,
   never one merged blob. *(verified by live build: 47 edges / 19 nodes,
   lit lines {41, 51, 54, 55, 56, 66, 68, 70, 86, 132, 141, 152, 155})*
    - Search field: `east5_stzfxxb.charge_department` (script: EAST5_STZFXXB_M.sql — not a committed snapshot seed; verified by live build)
    - L54: `CASE WHEN a.CHARGE_DEPARTMENT ="GTRF_CoreTrade_SCSAI" THEN a.entd_opp_acct_name` — ✅ live build (edge: SCHEMA/structure @54, `bdm_acc_entrusted_payment@141` → `charge_department@51`) (edge: TABLE_FLOW/write value @54, `charge_department@51` → `output@41`) (edge: FILTER/row selection @54, `charge_department@51` → `output@41`)
    - L55 / L56 / L66 / L68 / L70 — the same trio at each arm's own line (`SCHEMA` belongs-to, `TABLE_FLOW/write value`, `FILTER/row selection`, all anchored @55 / @56 / @66 / @68 / @70 respectively)
    - L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — ✅ live build as well (edge: COMPUTED/compute step @51 ×5, `charge_department@51` → `stzfdxzh@53` / `stzfdxhm@65` / `stzfdxhh@67` / `stzfdxxm@69` / `BBZ@73`) (edge: SCHEMA/structure @51, `a@141` → the two `charge_department` chips @51)

    The cited lines in their SQL (the five CASE arms and their targets, verbatim):

        L53:           END As stzfdxzh, --受托支付对象账号   ← `stzfdxzh@53` — the L51 compute's target
        L55:         WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_acct_name,f.df_dfhm)   ← arm @55
        L56:         WHEN a.charge_department = "OPS_MBS" THEN REGEXP_REPLACE( --有英文字符   ← arm @56
        L65:           END AS stzfdxhm, --受托支付对象户名   ← `stzfdxhm@65`
        L66:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_no,f.df_dfxh)   ← arm @66
        L67:           ELSE a.entd_opp_bank_no END AS stzfdxhh, --受托支付对象行号   ← `stzfdxhh@67`
        L68:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_name,f.df_dfxm)   ← arm @68
        L69:           ELSE trim(a.entd_opp_bank_name) END As stzfdxxm, --受托支付对象行名   ← `stzfdxxm@69`
        L70:         CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark   ← arm @70
        L73:           END AS BBZ, --备注   ← `BBZ@73`
        L141:      FROM bdm_acc_entrusted_payment a --受托支付信息表   ← `a@141` / `bdm_acc_entrusted_payment@141` — the CASE's owner box

   *Note:* the audited CASE-arm set {54,55,56,66,68,70} holds — one arm, one line. The earlier note that the audited set "does not count" the L51 occurrence understated the payload: L51 IS served (the source CASE's own five compute steps into the target columns).

2. *4b, JOIN-ON AND-legs*: continuation legs of one JOIN get their own
   occurrence twins, so the highlight reaches the AND lines.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
    - L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served here in this closure (`data_dt` is a sibling field: its leg is dropped by the field-involvement rule 3b; the **full** view carries the JOIN/join step `bdm_acc_loan_info_sup@160` → `output@160` @202 that this closure excludes)
    - L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ nothing served here (same sibling drop; the **full** view carries the JOIN/join step @203)
    - L224 (PL): `AND a.p_dt = c.p_dt` — ✅ live build for the `ODS_CUPD_PLOAN_ACCTM_NEW5.p_dt` seed (not a committed snapshot seed): (edge: JOIN/join step @224 ×2, `p_dt@224` and `p_dt@220` → `output@19`) (edge: SCHEMA/structure @224 ×2, `a@220` → `p_dt@224`, `ODS_CUPD_PLOAN_ACCTM_NEW5@220` → `p_dt@220`)

    The cited lines in their SQL (SUP_M L160→L201, then PL L220→L224, verbatim):

        L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160` — the frame the join feeds
        L198:        loan_final p1
        L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199` — the join's owner box
        L200:        ON
        L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← the searched field's own leg
        L220:      FROM (select *,row_number() over (partition by acnw) as rn from ODS_CUPD_PLOAN_ACCTM_NEW5 …) a   ← `a@220` / `ODS_CUPD_PLOAN_ACCTM_NEW5@220`
        L223:      LEFT JOIN BDM_PUB_BRANCH D ON SUBSTR(A.HKZH,1,9) = D.org_no AND D.DATA_DT = '${load_date}' --贷款入账账号取值   ← the ON L224 continues
        L224:        AND a.p_dt = c.p_dt   ← the cited continuation leg

   *Note:* each leg of the searched field's own JOIN anchors its own line; a sibling leg's line stays dark in the searched field's closure.

3. *4d, no owner evidence*: `d.org_no_cbrc` @43 — the line's owner is
   already served by `c`'s NVL read; no duplicate twin is minted. ❌ No
   extra edge, no double highlight.
    - Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; the FULL-view rows below are what the flow-only view refuses to duplicate)
    - L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — (edge: SCHEMA/structure @43, `c@145` → `org_no_cbrc@43` and `d@148` → `org_no_cbrc@43` — **full view only**) (edge: TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41` — **full view only**)

    The cited lines in their SQL (the write box and the two NVL owners, verbatim):

        L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← `east5_stzfxxb@41` — the write target box
        L145:        LEFT JOIN bdm_pub_branch c --机构信息表   ← `c@145` / `bdm_pub_branch@145`
        L148:        LEFT JOIN bdm_pub_branch d --机构信息表   ← `d@148`

   *Note:* the old text cites this as L42 — that line is a SQL comment in the sample; the NVL line is L43. The paren-scope owner rule mints no second twin for `d.`'s bare occurrence.

**§5 FOLD — which carrier represents the group**

1. *5a, multi-anchor*: `lending_ref` joining `loan_final` at lines
   95/117/150/156 → FOUR JOIN-anchor lines, one edge per line (the RC-B
   fix: one merged edge used to hide three of the four).
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L95: `ON p1.lending_ref = accu.vlookup_key_value` — ✅ (edge: JOIN/join step @95, `lending_ref@13` → `loan_final@64`)
    - L117: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ (edge: JOIN/join step @117, `lending_ref@13` → `loan_final@64`)
    - L150: `ON RPAD(p4.iiapty,3,'')||p4.iiblno = p1.lending_ref` — ✅ (edge: JOIN/join step @150, `lending_ref@13` → `loan_final@64`)
    - L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156 ×2 — `lending_ref@13` and `lending_ref@82`, one per occurrence on the two sides of the predicate)

    The cited lines in their SQL (the two occurrences and the shared target, verbatim):

        L13:           lending_ref   ← `lending_ref@13` — the p1-side occurrence
        L64:       ,loan_final AS (   ← `loan_final@64` — the shared JOIN target box
        L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← `lending_ref@82` — the p6-side occurrence

   *Note:* one edge per occurrence line — no merged blob.

2. *5b, keeper-line*: among carriers of one group, the one standing on
   the chip's own line wins the fold (Fix H) — the served edge's anchor
   is the line you'd click.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
    - L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198`)

    The cited lines in their SQL (the instance the projection belongs to, verbatim):

        L84:           bdm_acc_loan_info p1   ← `p1@84` — the CTE instance whose projection L163 is
        L163:        ,p1.lending_ref -- 借据编号   ← the chip's own line
        L198:        loan_final p1   ← the outer query's instance

   *Note:* the chip's own line (@163) carries its belongs-to; the read that consumes it anchors at the instance's line (@198), never at a projection line.

3. *5d, claimed-together*: the LFS108 NOT-IN filter — a group whose line
   another relationship already claims earns no second edge. ❌ One
   story per line.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L48: `AND p1.lending_ref NOT IN (` — ❌ no second edge served @48 (canonical row LFS108 stays LIVE as `FILTER lending_ref@13` → `⟐subq@0` anchor 48, but the served closure carries nothing here — the L41 join carrier already claims this story)
    - L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ the line the flow-only closure leaves dark: no edge at all in this closure (the **full** view serves JOIN/join step @41)

    The cited lines in their SQL (the NOT-IN's occurrences, verbatim — its ⟐subq chip is a line-0 node, rule 5c):

        L13:           lending_ref   ← `lending_ref@13` — the occurrence the NOT-IN filter cites
        L48:               AND p1.lending_ref NOT IN (   ← the NOT-IN's own line
        L49:                 SELECT
        L50:                   DISTINCT lending_ref   ← the subquery's own occurrence

   *Note:* one story per line — the closure never mints a second edge for a line another relationship already claims.

## 4. TWINS rules — the same field at many lines

> **In plain words:** the extractor collects a field's repeated references into ONE
> variable, and one variable can anchor only ONE line — so a field appearing at 5
> lines would light only 1. A **twin** is a shadow copy registered for exactly one
> other line, so that line lights too. The rules police it: every real occurrence
> gets its line (4a) — including each AND-continuation line of a JOIN ON (4b) — a
> line that is already lit gets no second light (4c), and a bare occurrence with no
> clause owner of its own earns none (4d). One light per line the field really
> occupies — never zero, never two, never fabricated.

| # | Rule | Shown? | Example |
|---|---|---|---|
| 4a | Each occurrence lights at its **own line** | ✅ | EAST5 `charge_department`'s CASE arms (L54/55/56/66/68/70): one arm, one line; the closure also lights L51 (the source CASE's own compute steps) — live build 47 edges / 19 nodes |
| 4b | **JOIN-ON AND-continuation legs** (family-4 twins) | ✅ | SUP_M L201: `p2.lending_ref = p1.lending_ref` — the searched field's own leg anchors its own line (the sibling legs @202/@203 stay dark — rule 3b); PL L224 `AND a.p_dt = c.p_dt` — the continuation leg of the searched field's own JOIN serves 2 JOIN + 2 SCHEMA rows (live build) |
| 4c | A line already anchored by a surviving var — no duplicate | ❌ | The L82 NVL read: anchored once |
| 4d | A twin with **no owner evidence** is not minted | ❌ | EAST5 L43: `d.org_no_cbrc` inside `NVL(c.org_no_cbrc,d.org_no_cbrc)` — a bare occurrence with no clause owner of its own earns no twin (the paren-scope owner rule); L42 is a SQL comment in the sample |
| 4e | **Producer-occurrence anchoring** (USER APPROVED 2026-09-02 — landed, v3.3.199 commit `8c5c6a4`): an edge carrying the searched field's value from a producer column anchors at the occurrence INSIDE the searched field's own expression | ✅ | EAST5 × `BBZ`: the `a.ccy_code` producer edge anchors **L71** (arm-2 condition `A.ccy_code<>B.ccy_code`), never **L47** (`a.ccy_code AS bz` — the sibling column `bz`'s birth line); the `a.charge_department` edge anchors **L70** (arm-1 condition), never the `stzfdxzh` CASE's L51 |

---

## 5. FOLD rules — which carrier represents the group

| # | Rule | Shown? | Example |
|---|---|---|---|
| 5a | **Multi-anchor**: N occurrences joining the same target at N lines → N edges | ✅ | SUP_M: `lending_ref` anchors FIVE join lines — L95, L117, L150, L156 (one edge per side, ×2), L201 → 6 JOIN edges; L41's `CONCAT(...)=p1.lending_ref` serves nothing in this closure (that anchor is a **full**-view fact) **(RC-B, fixed)** |
| 5b | **Fix H keeper-line**: a carrier at the chip's own line wins | ✅ | — |
| 5c | **Line-0 guard**: a carrier with no line never anchors | ❌ | The TVF-alias class — now fixed to carry real lines (M-T1) |
| 5d | **Claimed-together**: a group whose line another relationship claims earns no extra edge | ❌ | The LFS108 NOT-IN filter |
| 5e | **Cross-statement instance duplication**: an occurrence with a qualifying owner instance is not duplicated onto a different statement's instance | ❌ **(J2 fixing — defect A)** | SUP_M @202: the `data_dt` occurrence is owned by `p2@199` (the join) — not duplicated onto the L223 job-log instance |
| 5f | **Foreign-owner guessed fold**: an occurrence is never re-parented onto the searched compound without owner evidence | ❌ **(J2 fixing — defect B)** | PL @250: `T_BRANCH.data_dt`'s edges served as `bdm_acc_loan_info.data_dt` — the FSB phantom class |

---

## 6. GATE rules — the value-cone excludes what the value never reaches

| # | Rule | Shown? | Example |
|---|---|---|---|
| 6a | **Cross-table same-name seeds** | ❌ | Searching `bdm_acc_loan_info.data_dt`: the `c/d/e.data_dt` chips excluded — **(RC-A, fixed)** |
| 6b | **Foreign statement trunks**: a statement that doesn't carry the field's value doesn't enter | ❌ | The job-log DML trunk drops from `lending_ref`'s closure; `rrcdm ↓ EAST5` stays 3/3 (@179/@189/@190). 7-A carve-out: a trunk whose INSERT writes the SEARCHED column enters by its write leg (`data_dt` @253 in PL, `p_dt` @179 in EAST5) |
| 6c | **Foreign-owner folds** respected | ❌ | PL @250: edges attribute to `T_BRANCH`, never the searched compound — **(J2 fixing)** |
| 6d | **Alias/feeder-box scope**: an alias compound and its row-source chain enter only while the searched field's producing expression reads through that alias | ❌ otherwise | EAST5 × `BBZ`: `a@141` stays (BBZ's arms read `a.*`); `e@152`/`f@155` and their chain legs drop (they feed `stzfdxzh/stzfdxhm/stzfdxhh/stzfdxxm` only) — the carrier-is-None fix (2026-09-02) |
| 6e | **Own-segment rule**: an edge is served only if its OWN carried hop segment (`‖…‖`, `_src_label`/`_path_hops`) is the searched field's participation | ❌ otherwise | EAST5 × `p_dt`: the job-log trunk `‖⟐output@179 → rrcdm_job_log_exec_par@179‖` drops even though its display endpoints render as the searched table's pair — `p_dt`'s only role is the @190 filter. The evidence rides the edge; the carrier-is-None fix (2026-09-02) reads it |

---

## Rule-by-rule: two real examples + script segments for every item (1a–6e)

Every rule item with **two distinct real cases** and the **actual SQL** they
come from (line numbers = the current `samples/sql_sample_v1/` files).
Deep-dive sections above (§3a in full, Worked examples) are cross-referenced.

### §1 SEEDS

**1a — own-table occurrence seeds.**

*Example 1 — the write-projection occurrence seeds (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L13: `lending_ref` — ✅ (edge: SCHEMA/structure @13, `rollover_loan_info@9` → `lending_ref@13`) (edge: REF/value copy @13, `lending_ref@13` → `lending_ref@82`)
- L19: `AND lending_ref IN (` — ✅ (edge: FILTER/filter step @19, `lending_ref@13` → `rollover_loan_info@9`) (edge: SCHEMA/structure @19, `bdm_acc_loan_info@16` → `lending_ref@13`)
- L162: `p1.internal_key` — (no edge served @162 — not the searched field)

The cited lines in their SQL (the seed's CTE context, verbatim):

```sql
L9:        WITH rollover_loan_info AS (   ← `rollover_loan_info@9` — the CTE box the seed belongs to
L12:         SELECT
L13:           lending_ref   ← the seed chip's own line
L16:             bdm_acc_loan_info   ← `bdm_acc_loan_info@16` — the CTE's source box
L19:             AND lending_ref IN (
```

*Note:* the projection occurrence seeds the closure; the IN-predicate line lights with it (canonical LFS107).

*Example 2 — the partition-key occurrence seeds (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`)

  context: complete in the rows above.

*Note:* the INSERT's own PARTITION key occurrence is the seed; the whole closure for this script is these 7 edges (@41/179/189/190).

**1b — alias/TVF expansion (#399).**

*Example 1 — the TVF form, payload-verified (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` — the snapshot seed; the TVF-alias form `a.cust_no` sits inside this closure (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: TABLE_FLOW/chain (read into output) @1103, `a@1103` → `output(exists13)@1103`) (edge: TABLE_FLOW/chain (VT chain) @1103, `output(exists13)@1103` → `output@867`) (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`) (edge: REF/read @1103, `cust_no@1105` → `a@1103`)
- L1104: `LEFT JOIN bdm_acc_deposit_acct b` — ✅ (edge: ALIAS/chain (alias hop) @1104, `bdm_acc_deposit_acct@1104` → `b@1104`) (edge: REF/read @1104, `cust_no@1105` → `b@1104`)
- L1105: `ON a.cust_no = b.cust_no` — ✅ (edge: JOIN/join step @1105 ×2, `cust_no@1105` → `output(exists13)@1103` — one per predicate side) (edge: SCHEMA/structure @1105, `a@1103` / `b@1104` / `b@1111` → `cust_no@1105`) (edge: COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`)

The cited lines in their SQL (the TVF chain and the far endpoints, verbatim):

```sql
L867:      INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}',CHARGE_DEPARTMENT='GTRF_RFN')   ← `output@867` — the statement the EXISTS chain feeds
L1103:       WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a   ← `a@1103` / `v_bdm_customer_all@1103`
L1104:         LEFT JOIN bdm_acc_deposit_acct b   ← `b@1104`
L1105:         ON a.cust_no = b.cust_no   ← the cited ON line
L1110:         SELECT 1
L1111:           FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS b   ← `b@1111`
L1119:       END AS DM_FLAG2  -- 境内外标识"F"境外/"I"境内   ← `DM_FLAG2@1119`
```

*Note:* the TVF box `v_bdm_customer_all@1103` and its alias `a@1103` both enter the closure — the alias's owning entities seed (#399).

*Example 2 — the plain alias-qualified form (RFN, the FSC-2 case)*

- Search field: `a.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql — not a committed snapshot seed; verified by live build, which matches: 122 edges / 39 nodes)
- L1105: `ON a.cust_no = b.cust_no` — ✅ live build (edge: JOIN/join step @1105 ×2, `cust_no@1099` and `cust_no@1105` → `output(exists13)@1103` — one per predicate side) (edge: COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`) (edge: SCHEMA/structure @1105 ×4 — `a@1097` / `a@1103` / `b@1104` / `b@1111` → the two `cust_no` chips)

The cited lines in their SQL (both EXISTS blocks' aliases and the far endpoints, verbatim):

```sql
L867:      INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '${load_date}',CHARGE_DEPARTMENT='GTRF_RFN')   ← `output@867`
L1097:       WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a   ← `a@1097` — the FIRST EXISTS's alias
L1099:         ON a.cust_no = b.cust_no   ← `cust_no@1099` — the first EXISTS's ON
L1105:         ON a.cust_no = b.cust_no   ← the cited line
L1110:         SELECT 1
L1111:           FROM ODS_GDC_DATAMASK_WHITE_LIST_CDT_PSV_OPSS b   ← `b@1111`
L1119:       END AS DM_FLAG2  -- 境内外标识"F"境外/"I"境内   ← `DM_FLAG2@1119`
```

*Note:* the doc's own record stands: before the model-persistence fix this seed was LOST (`search_matched: false`, the whole 1053-node graph served — the RFN **full** view is exactly those 1053 nodes / 6760 edges); after it the alias-qualified seed matches again — its own 122-edge / 39-node closure, beside the snapshot seed's 40-node / 82-edge one.

**1c — cross-table same-name does NOT seed.**

*Example 1 — the sup self-join leg SEEDS (that is 2e, not 1c)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ `p2` IS the searched table's sup instance (edge: REF/read @199, `lending_ref@201` → `p2@199`) (edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160`)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served @202 in this closure (`lending_ref` is the seed here, so the sibling leg drops; the **full** view carries SCHEMA/structure `p2@199` → `data_dt@160`, reason `‖p2.data_dt@L202‖`, plus the JOIN/join step `bdm_acc_loan_info_sup@160` → `output@160`)

The cited lines in their SQL (SUP_M L160→L202, verbatim):

```sql
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160` — the frame the join feeds
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← the searched field's own leg
L202:          AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD') -- 取前一天的数据   ← the sibling leg, dark here
```

*Example 2 — the foreign same-name column does NOT seed (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L221: `LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'` — ❌ (no edge served @221 — `c.p_dt` is a same-NAME, different-TABLE column of `ODS_CUPD_PLOAN_APS_CREDINF5`; the **full** view carries only that sibling chip's own SCHEMA/structure `c@221` → `p_dt@221` here)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19` — the searched table's own occurrence, for contrast)

The cited lines in their SQL (the searched table's own box, verbatim):

```sql
L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19` — the searched table's own box
```

### §2 VALUE

**2a — reads.**

*Example 1 — the SELECT-projection read (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
- L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198`)

The cited lines in their SQL (the two p1 instances and the projection, verbatim):

```sql
L84:           bdm_acc_loan_info p1   ← `p1@84` — the CTE instance the projection reads
L163:        ,p1.lending_ref -- 借据编号   ← the chip's own line
L198:        loan_final p1   ← the outer query's instance
```

*Note:* the projection occurrence lights at its own line (@163); the read that consumes it lands on the instance line (@198).

*Example 2 — the read that births the output column (DL × `lending_ref`)*

- Search field: `temp_kmbh_gl.lending_ref` (script: BDM_ACC_LOAN_INFO_Digitallending.sql)
- L99: `INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)',CHARGE_DEPARTMENT='WPB_CDT_Digitallending')` — ✅ (edge: TABLE_FLOW/write leg @99, `output@99` → `bdm_acc_loan_info@99`)
- L101: `A.acctnbr AS LENDING_REF` — ✅ (edge: TABLE_FLOW/write value @101, `LENDING_REF@101` → `output@99`) (edge: SCHEMA/structure @101 ×2, `output@99` → `LENDING_REF@101`) (edge: REF/read @426, `LENDING_REF@101` → `ods_ccb_cb_loan_acctloan@426` — the read that feeds this write)

The cited lines in their SQL (DL L99→L101 and the read at L426, verbatim):

```sql
L99:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)',CHARGE_DEPARTMENT=…)   ← `output@99` / `bdm_acc_loan_info@99` — the write leg's two endpoints
L100:        SELECT   ← the SELECT head (serves nothing)
L101:        A.acctnbr AS LENDING_REF --借据编号   ← the cited projection
L426:        FROM ods_ccb_cb_loan_acctloan A   ← `ods_ccb_cb_loan_acctloan@426` — the read that feeds the write
```

*Note:* the old text cited "L100-101"; the INSERT is L99 and `SELECT` is L100 (which serves nothing). Canonical LFD3 pins the naming rule: no column list, so the SELECT alias IS the output column's name.

**2b — writes.**

*Example 1 — the value lands in the write target (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
- L160: `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)` — ✅ (edge: TABLE_FLOW/write leg @160, `output@160` → `bdm_acc_loan_info_sup@160`) (edge: ALIAS/chain (alias hop) @160, `bdm_acc_loan_info_sup@160` → `p2@199`)

The cited lines in their SQL (SUP_M L64→L199, verbatim):

```sql
L64:       ,loan_final AS (   ← `loan_final@64` — the CTE the read lands in
L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← `lending_ref@82` — the read's source occurrence
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155`
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← the cited write
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199` — the alias hop's target
```

*Note:* the write leg is the searched field's own — the statement's INSERT edge is admitted because `lending_ref` is written into the target.

*Example 2 — the partition slot write (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`)

  context: complete in the rows above.

**2c — computes.**

*Example 1 — the field inside a join-key expression (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ❌ verified: this flow-only closure serves nothing at L41, while the **full** view carries JOIN/field flow (join step) @41, `bdm_acc_loan_info@16` → `p2@40`, reason `‖p1.lending_ref@L41 → CONCAT(…)‖`

The cited lines in their SQL (the two boxes the full-view join edge joins, verbatim):

```sql
L16:             bdm_acc_loan_info   ← `bdm_acc_loan_info@16` — the main table's box
L40:             ) p2   ← `p2@40` — the subquery alias the ON joins
```

*Note:* the main table's "@41" citation is a full-view fact; the served flow-only closure for `lending_ref` lights the same expression's *sibling* JOIN site at L117 instead.

*Example 2 — a CASE mask computes the field (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1117: `OR (regexp_instr(A.LOAN_IN_ACCT_NAME,'[A-Za-z]+$') >= 1 AND length(A.LOAN_IN_ACCT_NAME) <> lengthb(A.LOAN_IN_ACCT_NAME))` — ❌ verified: no edge served @1117 in this closure
- L1118: `THEN 'NI'` — ❌ verified: no edge served @1118
- L1119: `END AS DM_FLAG2` — ❌ verified: no edge anchored @1119 — the `DM_FLAG2@1119` chip is the TARGET of the compute steps, whose anchors are the field's own occurrence lines (@1105 and @1178)

The cited lines in their SQL (RFN L1105 / L1117→L1119 / L1178, verbatim):

```sql
L1105:         ON a.cust_no = b.cust_no   ← `cust_no@1105` — the compute step's source anchor
L1117:       OR (regexp_instr(A.LOAN_IN_ACCT_NAME,'[A-Za-z]+$') >= 1 AND length(A.LOAN_IN_ACCT_NAME) <> lengthb(…))   ← the mask's first leg
L1118:       THEN 'NI'   ← the mask's value
L1119:       END AS DM_FLAG2  -- 境内外标识"F"境外/"I"境内   ← the mask's target chip
L1178:       ,A.CUST_NO  -- 客户号   ← `cust_no@1178` — the second occurrence line whose compute step also lands on DM_FLAG2
```

*Note:* the same shape IS payload-visible in this same closure: RFN's own closure serves COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`, and again @1178 — the audited written-768 step of the doc's record. The mask's own three lines stay dark.

**2d — filters.**

*Example 1 — the searched field's own predicate (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19` — canonical F1)
- L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)

The cited lines in their SQL (the two endpoint boxes, verbatim):

```sql
L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19` — the searched table's own box
L253:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,…,STATUS,remarks)   ← `output@253` — the job-log frame the read-into-output edge targets
```

*Example 2 — its own predicate arm at its own line (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a committed snapshot seed; verified by live build: 39 edges / 14 nodes)
- L37: `AND podtao <> pofddt` — ✅ live build (edge: SCHEMA/structure @37, `ods_hub_lsacmsp@33` → `podtao@31`) (edge: FILTER/filter step @37, `podtao@31` → `output(p2)@31`)

The cited lines in their SQL (SUP_M L31→L37 inside the p2 subquery, verbatim):

```sql
L31:               SELECT podcg, poctcd, pogmab, poacb, poacs, poacx, podtao, poapty, poofla, pofddt, pocnlm, poclin   ← `podtao@31` — the field's own occurrence
L33:                 ods_hub_lsacmsp   ← `ods_hub_lsacmsp@33` — the subquery's source box
L37:                 AND podtao <> pofddt   ← the cited predicate
```

**2e — join keys.**

*Example 1 — the field IS the join operand (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
- L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156, `lending_ref@13` → `loan_final@64`) (edge: JOIN/join step @156, `lending_ref@82` → `loan_final@64`)

The cited lines in their SQL (the two sides' occurrences and the join, verbatim):

```sql
L13:           lending_ref   ← `lending_ref@13` — the p1 side
L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← `lending_ref@82` — the p6 side
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155`
L156:          ON p6.lending_ref = p1.lending_ref   ← the cited ON
```

*Example 2 — the operand edge at the join line (PL, searching `acnw`)*

- Search field: `ODS_CUPD_PLOAN_ACCTM_NEW5.acnw` (script: BDM_ACC_LOAN_INFO_PL.sql — not a committed snapshot seed; verified by live build: 23 edges / 13 nodes)
- L221: `LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'` — ❌ verified: no edge served @221 in this closure (the **full** view of this script does serve JOIN/field flow (join step) @221, `ODS_CUPD_PLOAN_APS_CREDINF5@221` → `output@19`, reason `‖c.sxxyh@L221 → ⟐ output@L19‖`, i.e. the *sxxyh* operand, not `acnw`). The closure's own JOIN anchor is L249 — `ON a.acnw = p2.arrangement_local_number …` — `JOIN/join step @249, acnw@21 → output@19`.

The cited lines in their SQL (PL L19/L21 and the closure's own JOIN anchor @249, verbatim):

```sql
L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `output@19` — the closure's output frame
L21:         SELECT distinct a.acnw AS LENDING_REF,  -- 借据号   ← `acnw@21` — the searched field's own occurrence
L249:        ON a.acnw = p2.arrangement_local_number AND p2.rn = 1   ← the closure's own JOIN anchor (`JOIN/join step @249, acnw@21 → output@19`)
```

**2f — group/window keys.**

*Example 1 — the group key decides grouping (PL, searching `product`)*

- Search field: `bdm_fin_lrr_key_base_info.product` (script: BDM_ACC_LOAN_INFO_PL.sql — not a committed snapshot seed; verified by live build: 10 edges / 9 nodes, lit lines {19, 33, 232, 234, 246})
- L243: `group by arrangement_local_number,` — ❌ verified: no edge served @243 (a sibling GROUP BY key; the **full** view carries its belongs-to SCHEMA row here)
- L244: `cb_pointer,` — ❌ verified: no edge served @244 (same sibling drop)
- L245: `account,` — ❌ verified: no edge served @245 (same sibling drop)
- L246: `product,` — ✅ live build (edge: SCHEMA/structure @246, `bdm_fin_lrr_key_base_info@234` → `product@232`) — CORRECTED 2026-09-02: the earlier text called this a **full**-view-only fact; the payload serves it in the FLOW-ONLY closure too, because it is the SEARCHED field's own belongs-to (the audited Reappears anchor), which rule 3a never drops
- L247: `lrr_key) km1` — ❌ verified: no edge anchored @247 in this closure (the **full** view carries the SUBQUERY/combine step `km1@247` → the output frame and the belongs-to `lrr_key@230` here)

The cited lines in their SQL (the SELECT list and FROM the closure cites, verbatim):

```sql
L230:          lrr_key,   ← `lrr_key@230`
L231:          account,
L232:          product,   ← `product@232` — the searched field's own projection
L233:          abs(sum(from_ytd_bal)) AS BAL
L234:        FROM bdm_fin_lrr_key_base_info bi   ← `bdm_fin_lrr_key_base_info@234` — the belongs-to's source box
```

*Example 2 — the window PARTITION key (DL, searching `acnw`)*

- Search field: `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` (script: BDM_ACC_LOAN_INFO_Digitallending.sql — not a committed snapshot seed; verified by live build: 41 edges / 18 nodes)
- L64: `,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN` — ✅ live build (edge: WINDOW/window step @64, `acnw@62` → `RN@64` — the OVER-line anchor) (edge: REF/field flow (value copy) @64, `RN@64` → `rn@76`) (edge: SCHEMA/structure @64, `ODS_CUPD_CLD_ACCTMASTER_NEW@65` → `acnw@62` — the audited Reappears anchor)

The cited lines in their SQL (DL L62→L76, verbatim):

```sql
L62:         SELECT p1.acnw AS lending_ref   ← `acnw@62` — the searched field's occurrence
L64:         ,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN   ← the cited OVER line
L65:         FROM ODS_CUPD_CLD_ACCTMASTER_NEW p1   ← `ODS_CUPD_CLD_ACCTMASTER_NEW@65` — the belongs-to's source box
L75:       ) t
L76:         WHERE t.rn = 1   ← `rn@76` — the window result's read-back line
```

**2g — named-but-literal write (✅ resolved by ruling 7-A, 2026-09-01).**

*Example 1 — the job-log data_dt (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — resolved by ruling 7-A (2026-09-01): the log never writes this field, so NOTHING shows — final state (no edge served @211)

  context: complete in the rows above.
- L212: `SELECT` — resolved by ruling 7-A: nothing shows (final state)
- L213: `'$(load_date)' AS data_dt` — resolved by ruling 7-A: nothing shows (final state)

*Example 2 — the same shape the engine DOES serve (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ ruling 7-A (write leg only, 2026-09-01): shown — (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253` — canonical P16)
- L254: `SELECT '${load_date}' AS data_dt,` — ✅ ruling 7-A: shown — (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253` — canonical V2) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254` — canonical M1)

  context: complete in the rows above.

*Note:* post-7-A the two examples agree with each other — they search DIFFERENT fields. PL searches `data_dt`, a column the log writes (write leg @253, value @254); SUP_M searches `lending_ref`, which the log never writes, so the statement contributes nothing (corollary 3). EAST5 (`p_dt`) serves the same shape at @179.


**2h — provenance-linked AS-alias routing (landed 2026-09-02, the F2 chain repair).**

*Example 1 — the alias's output legs stay served (EAST5 × `entd_paym_dt`)*

- Search field: `bdm_acc_entrusted_payment.entd_paym_dt` (script: EAST5_STZFXXB_M.sql — verified by live build)
- L50: `REPLACE(a.entd_paym_dt,"_","") As stzfrq` — ✅ four edges serve on this line and the value chain stays WHOLE through the alias: (edge: TRANSFORM/compute step @50, `entd_paym_dt@50` → `stzfrq@50` — the searched value flows INTO the alias) (edge: TABLE_FLOW/write value @50, `stzfrq@50` → `output@41` — the alias's value leg to the output frame) (edge: SCHEMA/structure @50, `output@41` → `stzfrq@50` — the frame's membership of the alias chip) (edge: SCHEMA/structure @50, `a@141` → `entd_paym_dt@50` — the searched field's own belongs-to)

*Example 2 — the counter-case: a sibling's alias keeps nothing (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ❌ the alias `reserved_field8`'s ⟐output legs are DROPPED (3b): its value is the literals `'Rollover2'`/`''`, NOT the searched field's value — provenance fails, so the alias's output legs (its L183 write projection, its frame membership) never serve (canonical LFS135/LFS143-145 REMOVED). Contrast with Example 1: there the alias's value IS the searched field's value (the REPLACE reads `a.entd_paym_dt`), so the legs stay.

The cited lines in their SQL (EAST5 L41 → L50, verbatim):

```sql
L41:  INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← the write the chain reaches
L49:        REPLACE(a.entd_paym_amt,"_","") As stzfje,   ← a sibling alias: its output legs stay DROPPED (3b)
L50:        REPLACE(a.entd_paym_dt,"_","") As stzfrq,   ← the searched field's alias — its legs STAY (2h)
```

context: complete in the rows above.


### §3 SIBLINGS (post-ruling)

**3a — sibling belongs-to (dropped by the 2026-09-01 ruling).**

*Example 1 — `reserved_field8` is BORN on `lending_ref`'s own read line (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L80: `,p1.issue_dt` — (no edge served @80)
- L81: `,p1.loan_ori_maturity_dt` — (no edge served @81)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — canonical LFS133) (edge: SCHEMA/structure @82, `p6@155` → `lending_ref@82` — canonical LFS134) (dropped — USER RULING 2026-09-01: the sibling belongs-to SCHEMA/structure `loan_final@64` → `reserved_field8@82`, still served by the **full** view at this line — canonical LFS135 REMOVED)
- L183: `,p1.reserved_field8 AS reserved_field8` — (dropped — USER RULING 2026-09-01: the three sibling belongs-to rows SCHEMA/structure `p1@29` / `p1@84` / `p1@198` → `reserved_field8@82` — canonical LFS143/144/145 REMOVED) (dropped — field-involvement rule 3b: the write-projection read leg and the ⟐output membership, which the **full** view carries as `bdm_acc_loan_info_sup@160` → `reserved_field8@183` and `output@160` → `reserved_field8@82`)

The cited lines in their SQL (the alias instances and the write the dropped edges cite, verbatim):

```sql
L29:               bdm_acc_loan_info p1   ← `p1@29`
L64:       ,loan_final AS (   ← `loan_final@64`
L84:           bdm_acc_loan_info p1   ← `p1@84`
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155`
L156:          ON p6.lending_ref = p1.lending_ref
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `bdm_acc_loan_info_sup@160` / `output@160`
L183:        ,p1.reserved_field8 AS reserved_field8 -- rollover业务标识（修改到期日期）   ← the sibling's write projection
L198:        loan_final p1   ← `p1@198`
```

*Example 2 — `charge_department` is a DYNAMIC partition (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (dropped — USER RULING 2026-09-01: the sibling belongs-to SCHEMA/structure `east5_stzfxxb@41` → `CHARGE_DEPARTMENT@41` and `output@41` → `CHARGE_DEPARTMENT@41` ×2, still served by the **full** view here)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — USER RULING 2026-09-01: the source-CASE belongs-to SCHEMA/structure `a@141` → `charge_department@51`, still served by the **full** view) (dropped — field-involvement rule 3b: the sibling's feeding expression)

The cited lines in their SQL (the sibling's owner box, verbatim):

```sql
L141:      FROM bdm_acc_entrusted_payment a --受托支付信息表   ← `a@141` — the sibling's owner box
```

**3b — sibling value legs.**

*Example 1 — `reserved_field8`'s legs: born @82, written @183, read back at the p2 join (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the seed's own leg, kept) (dropped — field-involvement rule 3b: the sibling's own CASE value legs)
- L183: `,p1.reserved_field8 AS reserved_field8` — (dropped — field-involvement rule 3b: the write-projection read leg and ⟐output membership the **full** view carries here)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — (dropped — field-involvement rule 3b: the sibling's read-back leg; this line serves the seed's own `REF/read @199, lending_ref@201 → p2@199` and `TABLE_FLOW/chain (read into output) @199` instead)

The cited lines in their SQL (SUP_M L199→L201, verbatim):

```sql
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← the seed's own read-back leg's line
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← `lending_ref@201` — the read-back's source occurrence
```

*Example 2 — `charge_department`'s feeding expression and output routing (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — field-involvement rule 3b: the sibling's COMPUTED/compute step `bdm_acc_entrusted_payment@141` → `east5_stzfxxb@41` with reason `‖a.entd_opp_acct_no@L51 → stzfdxzh@L53‖` — CORRECTED 2026-09-02, the payload's reason names the COALESCE arm, not `charge_department`; what marks the line as the sibling's is its belongs-to `a@141` → `charge_department@51`, which the **full** view carries)

The cited lines in their SQL (EAST5 L41 / L51→L53 / L141, verbatim):

```sql
L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← `east5_stzfxxb@41` — the write box the full-view compute leg routes into
L51:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)   ← the sibling's feeding CASE
L53:           END As stzfdxzh, --受托支付对象账号   ← `stzfdxzh@53` — the compute's target
L141:      FROM bdm_acc_entrusted_payment a --受托支付信息表   ← `a@141` — the sibling's owner box
```

**3c — sibling chips.**

*Example 1 — the chip survives while a kept edge touches it (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ✅ chip in closure (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the ONE edge the sibling chip carries)

  context: complete in the rows above.

*Note:* `reserved_field8@82` stays because the seed's own CASE feeds it — edge-anchored by the searched field's flow, never by its belongs-to ("this column exists on this box" is a full-view fact).

*Example 2 — the edge-less co-filter chip is pruned with its belongs-to (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`)
- L265: `AND charge_department = 'OPS_CLBS_PLoan';` — (dropped — USER RULING 2026-09-01: no edge, and the edge-less `charge_department@265` chip pruned with it; canonical point 26)

The cited lines in their SQL (the two endpoint boxes, verbatim):

```sql
L19:       INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')   ← `bdm_acc_loan_info@19`
L253:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,…,STATUS,remarks)   ← `output@253`
```

### §4 TWINS

**4a — per-occurrence lines.**

*Example 1 — the CASE arms light at their own lines (EAST5, searching `charge_department`)*

- Search field: `east5_stzfxxb.charge_department` (script: EAST5_STZFXXB_M.sql — not a committed snapshot seed; verified by live build: 47 edges / 19 nodes) — CORRECTED 2026-09-02: the earlier text called these rows "full view only"; the flow-only closure for THIS seed serves them, because here `charge_department` is the SEARCHED field
- L54: `CASE WHEN a.CHARGE_DEPARTMENT ="GTRF_CoreTrade_SCSAI" THEN a.entd_opp_acct_name` — ✅ live build (edge: SCHEMA/structure @54, `bdm_acc_entrusted_payment@141` → `charge_department@51`) (edge: TABLE_FLOW/write value @54, `charge_department@51` → `output@41`) (edge: FILTER/row selection @54, `charge_department@51` → `output@41`)
- L55 / L56 / L66 / L68 / L70 — the same trio at each arm's own line
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(...)` — ✅ live build (edge: COMPUTED/compute step @51 ×5, `charge_department@51` → `stzfdxzh@53` / `stzfdxhm@65` / `stzfdxhh@67` / `stzfdxxm@69` / `BBZ@73`) (edge: SCHEMA/structure @51, `a@141` → the `charge_department` chips @51)

The cited lines in their SQL (the five CASE arms and their targets, verbatim):

```sql
L53:           END As stzfdxzh, --受托支付对象账号   ← `stzfdxzh@53` — the L51 compute's target
L55:         WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_acct_name,f.df_dfhm)   ← arm @55
L56:         WHEN a.charge_department = "OPS_MBS" THEN REGEXP_REPLACE( --有英文字符   ← arm @56
L65:           END AS stzfdxhm, --受托支付对象户名   ← `stzfdxhm@65`
L66:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_no,f.df_dfxh)   ← arm @66
L67:           ELSE a.entd_opp_bank_no END AS stzfdxhh, --受托支付对象行号   ← `stzfdxhh@67`
L68:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_name,f.df_dfxm)   ← arm @68
L69:           ELSE trim(a.entd_opp_bank_name) END As stzfdxxm, --受托支付对象行名   ← `stzfdxxm@69`
L70:         CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark   ← arm @70
L73:           END AS BBZ, --备注   ← `BBZ@73`
L141:      FROM bdm_acc_entrusted_payment a --受托支付信息表   ← `a@141` / `bdm_acc_entrusted_payment@141` — the CASE's owner box
```

*Note:* each occurrence at its own line, never one merged blob. L51 is served too — the earlier "the audited lit set does not count L51" note was an audit-set statement, not a payload statement.

*Example 2 — two occurrences → two twins, two lines (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a committed snapshot seed; verified by live build: 39 edges / 14 nodes)
- L37: `AND podtao <> pofddt` — ✅ live build (edge: SCHEMA/structure @37, `ods_hub_lsacmsp@33` → `podtao@31`) (edge: FILTER/filter step @37, `podtao@31` → `output(p2)@31` — the predicate chip's line)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ live build (edge: SCHEMA/structure @41 ×3, `p2@40` / `ods_hub_lsacmsp@33` / `p2@199` → the two `podtao` chips @31/@41) (edge: JOIN/join step @41 ×3, `podtao@41` / `podtao@31` / `ods_hub_lsacmsp@33` → `output(subq)@26`) (edge: REF/read @41, `podtao@41` → the `CONCAT(...)` expression chip)

The cited lines in their SQL (SUP_M L26→L41 and L199, verbatim):

```sql
L26:             DISTINCT lending_ref   ← `output(subq)@26` — the subquery's output frame
L31:               SELECT podcg, poctcd, pogmab, poacb, poacs, poacx, podtao, poapty, poofla, pofddt, pocnlm, poclin   ← `podtao@31`
L33:                 ods_hub_lsacmsp   ← `ods_hub_lsacmsp@33`
L37:               AND podtao <> pofddt   ← (the row above — the sibling predicate)
L40:             ) p2   ← `p2@40` — the subquery alias
L41:             ON CONCAT(p2.poctcd,p2.pogmab,…,LPAD(p2.podtao,8,'0')) = p1.lending_ref   ← the cited join line
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199` — the third alias instance
```

**4b — JOIN-ON AND-legs.**

*Example 1 — one JOIN, three AND-legs (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served here in this closure (`data_dt` is a sibling: field-involvement rule 3b; the **full** view carries the leg's JOIN/join step @202, `bdm_acc_loan_info_sup@160` → `output@160`)
- L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ nothing served here (same sibling drop; the **full** view carries JOIN/join step @203)

The cited lines in their SQL (SUP_M L160→L203, verbatim):

```sql
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← the searched field's own leg
L202:          AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD') -- 取前一天的数据   ← the sibling leg, dark
L203:          AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'   ← the sibling leg, dark
```

*Note:* the searched field's own leg anchors its own line; a sibling leg's line is dark in this closure.

*Example 2 — the AND-continuation leg (PL, searching `p_dt`)*

- Search field: `ODS_CUPD_PLOAN_ACCTM_NEW5.p_dt` (script: BDM_ACC_LOAN_INFO_PL.sql — not a committed snapshot seed; verified by live build: 10 edges / 6 nodes)
- L224: `AND a.p_dt = c.p_dt` — ✅ live build (edge: JOIN/join step @224 ×2, `p_dt@224` and `p_dt@220` → `output@19` — one per predicate side) (edge: SCHEMA/structure @224 ×2, `a@220` → `p_dt@224` and `ODS_CUPD_PLOAN_ACCTM_NEW5@220` → `p_dt@220`)

The cited lines in their SQL (PL L220→L224, verbatim):

```sql
L220:      FROM (select *,row_number() over (partition by acnw) as rn from ODS_CUPD_PLOAN_ACCTM_NEW5 …) a   ← `a@220` / `ODS_CUPD_PLOAN_ACCTM_NEW5@220`
L223:      LEFT JOIN BDM_PUB_BRANCH D ON SUBSTR(A.HKZH,1,9) = D.org_no AND D.DATA_DT = '${load_date}' --贷款入账账号取值   ← the ON L224 continues
L224:        AND a.p_dt = c.p_dt   ← the cited continuation leg
```

*Note:* L224 is the JOIN's own continuation leg (the `ON` is at L223); L221's `c.p_dt` sits on its own JOIN line, not a continuation.

**4c — no duplicate anchor.**

*Example 1 — the NVL read is anchored ONCE (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ✅ (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the seed's own edge; no twin re-anchors the line) (edge: SCHEMA/structure @82, `p6@155` → `lending_ref@82`)

The cited lines in their SQL (the alias the belongs-to edge comes from, verbatim):

```sql
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155` — the alias the belongs-to comes from
```

*Example 2 — the LPAD twin anchors its line once (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a committed snapshot seed; verified by live build: 39 edges / 14 nodes)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ live build, anchored once per relationship (edge: REF/read @41, `podtao@41` → the `CONCAT(...)` expression chip) (edge: JOIN/join step @41, `podtao@41` → `output(subq)@26`) — no twin duplicates either edge

The cited lines in their SQL (SUP_M L26 / L40→L41 / L199, verbatim):

```sql
L26:             DISTINCT lending_ref   ← `output(subq)@26`
L40:             ) p2   ← `p2@40`
L41:             ON CONCAT(p2.poctcd,p2.pogmab,…,LPAD(p2.podtao,8,'0')) = p1.lending_ref   ← the cited line
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
```

**4d — no owner evidence → no twin.**

*Example 1 — the paren-scope owner rule (EAST5, searching `org_no_cbrc`)*

- Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; the FULL-view rows below are what the flow-only view refuses to duplicate)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — (full view only: SCHEMA/structure @43, `c@145` → `org_no_cbrc@43` and `d@148` → `org_no_cbrc@43`; TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41`)

The cited lines in their SQL (EAST5 L41 / L43 / L145 / L148, verbatim):

```sql
L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← `east5_stzfxxb@41`
L43:         SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh, --金融许可证号   ← the cited line
L145:        LEFT JOIN bdm_pub_branch c --机构信息表   ← `c@145` / `bdm_pub_branch@145`
L148:        LEFT JOIN bdm_pub_branch d --机构信息表   ← `d@148`
```

*Note:* the old text cites L42 — that line is a SQL comment in the sample; the NVL line is L43. `d.`'s bare occurrence earns no second twin.

*Example 2 — the outer group never claims a paren-scope line (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a committed snapshot seed; verified by live build: 39 edges / 14 nodes)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ live build, and every served row here belongs to the expression's own scope (edge: REF/read @41, `podtao@41` → the `CONCAT(...)` expression chip) (edge: SCHEMA/structure @41, `p2@40` and `p2@199` → `podtao@41`) (edge: JOIN/join step @41, `podtao@41` → `output(subq)@26`) — `_paren_scope_bound` / `_scope_line_owner` keep the line with LPAD(...)'s own scope; the outer group claims none of them

The cited lines in their SQL (SUP_M L26 / L40→L41 / L199, verbatim):

```sql
L26:             DISTINCT lending_ref   ← `output(subq)@26`
L40:             ) p2   ← `p2@40`
L41:             ON CONCAT(p2.poctcd,p2.pogmab,…,LPAD(p2.podtao,8,'0')) = p1.lending_ref   ← the cited line
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
```


**4e — producer-occurrence anchoring (landed 2026-09-02, Team 4E — v3.3.199, commit `8c5c6a4`).**

> **The rule in one picture** — the producer column appears at two lines; the edge
> lights where BBZ's expression READS it, not where the column first appears:
>
> ```sql
> L47:  a.ccy_code AS bz,            ← WRONG anchor (pre-4e): births the sibling
>                                       column `bz`, not BBZ's operand
> L51:  CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(…)
>                                     ← WRONG anchor (pre-4e): the stzfdxzh CASE
> L70:  CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark
>                                     ← CORRECT: arm-1 condition + THEN (a.remark)
> L71:      WHEN … AND A.ccy_code <> B.ccy_code THEN '…'‖B.ccy_code
>                                     ← CORRECT: arm-2 condition (A.ccy_code, B.ccy_code)
> L73:  END AS BBZ,
> ```
>
> Before: edges drawn `L47 → BBZ` and `L51 → BBZ` (mis-anchored). After: `L70 → BBZ`
> and `L71 → BBZ`. Same value story — only the anchor lines move to the arms that
> actually feed BBZ.

*Trace (EAST5 × `BBZ`, live build: 10 edges / 6 nodes)*

- Search field: `east5_stzfxxb.BBZ` (script: EAST5_STZFXXB_M.sql)
- L70: `CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark` — ✅ ×2 (edge: COMPUTED @70, `bdm_acc_entrusted_payment@141` → `BBZ@73` — `‖a.remark@L70 → BBZ@L73‖`: arm-1's THEN) (edge: COMPUTED @70, `bdm_acc_entrusted_payment@141` → `BBZ@73` — `‖a.charge_department@L70 → BBZ@L73‖`: arm-1's condition)
- L71: `WHEN a.TAG_PRIMARY_ACCOUNTABLE_PARTY="WSB_GTRF_CoreTrade" AND A.ccy_code<>B.ccy_code THEN …‖B.ccy_code` — ✅ ×3 (edge: COMPUTED @71, `bdm_acc_loan_info@142` → `BBZ@73` — `‖B.ccy_code@L71 → BBZ@L73‖`: the condition AND the THEN concat) (edge: COMPUTED @71, `bdm_acc_entrusted_payment@141` → `BBZ@73` — `‖a.TAG_PRIMARY_ACCOUNTABLE_PARTY@L71 → BBZ@L73‖`) (edge: COMPUTED @71, `bdm_acc_entrusted_payment@141` → `BBZ@73` — `‖A.ccy_code@L71 → BBZ@L73‖`: the 4e producer, anchored at its own arm)
- L73: `END AS BBZ` — ✅ (edge: own ⟐output membership @73) (edge: TABLE_FLOW/write value, `BBZ@73 → output@41`)
- History: the pre-4e engine anchored these producers at **L47** (`bz`'s birth line) and **L51** (the `stzfdxzh` CASE's line) — sibling columns' expressions. Post-4e both anchor at their own arm lines; context: complete in the rows above.

### §5 FOLD

**5a — multi-anchor (N lines → N edges).**

*Example 1 — three join sites in the CTE zone, one edge per line (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L95: `ON p1.lending_ref = accu.vlookup_key_value` — ✅ (edge: JOIN/join step @95, `lending_ref@13` → `loan_final@64`)
- L117: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ (edge: JOIN/join step @117, `lending_ref@13` → `loan_final@64`)
- L150: `ON RPAD(p4.iiapty,3,'')||p4.iiblno = p1.lending_ref` — ✅ (edge: JOIN/join step @150, `lending_ref@13` → `loan_final@64`)
- L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156 ×2 — `lending_ref@13` and `lending_ref@82`, one per occurrence; canonical LFS117 + LFS138)

The cited lines in their SQL (the occurrences, the shared target and the fifth anchor, verbatim):

```sql
L13:           lending_ref   ← `lending_ref@13`
L64:       ,loan_final AS (   ← `loan_final@64`
L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← `lending_ref@82`
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← `lending_ref@201` — the note's fifth anchor
```

*Note:* the served closure anchors FOUR join lines into `loan_final` (5 edges, because L156 carries one per side) plus a fifth anchor at L201 — `JOIN/join step @201, lending_ref@201 → output@160`. L41's CONCAT join key (the main table's other cite) serves nothing in this flow-only closure: that anchor is a **full**-view fact.

*Example 2 — the same mechanism per AND-leg (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ sibling leg, dropped (field-involvement rule 3b; the **full** view carries the leg's JOIN/join step @202)
- L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ sibling leg, dropped (the **full** view carries JOIN/join step @203)

The cited lines in their SQL (SUP_M L160→L203, verbatim):

```sql
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← the searched field's own leg
L202:          AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD') -- 取前一天的数据   ← the sibling leg, dark
L203:          AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'   ← the sibling leg, dark
```

**5b — Fix H keeper-line.**

*Example 1 — the carrier standing ON the chip's own line wins (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
- L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198` — the alias-instance line, canonical LFS146's class)

The cited lines in their SQL (the instance the projection belongs to, verbatim):

```sql
L84:           bdm_acc_loan_info p1   ← `p1@84` — the CTE instance whose projection L163 is
L163:        ,p1.lending_ref -- 借据编号   ← the chip's own line
L198:        loan_final p1   ← the outer query's instance
```

*Note:* a carrier standing on a PROJECTION line does NOT win — L82/L163 are projection lines: the pinned Class-1 / LFS123 doctrine.

*Example 2 — the same fold on the write target's chip (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L254: `SELECT '${load_date}' AS data_dt,` — ✅ (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253`) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254`) — resolved by ruling 7-A (write leg only, 2026-09-01)
- L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253`)

  context: complete in the rows above.

**5c — line-0 guard.**

*Example 1 — the TVF alias carries a real line (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`)

  context: complete in the rows above.

*Note:* M-T1's `skip_parens` gave the alias its real call line — the TVF box is `v_bdm_customer_all@1103`, not `@0`.

*Example 2 — no served edge ever anchors line 0 (all five flagship closures)*

- Search field: all five flagship snapshots' seeds (scripts: Digitallending / PL / RFN / SUP_M / EAST5 — measured)
- (measured on the regenerated baselines: 173 flow-only edges / 86 nodes across the five closures, **0** with a highlight line < 1; `_pick_anchor` excludes `line_start < 1`)

  context: no cited SQL lines — this example is a measurement across the five closures, not a line trace.

*Note:* line 0 still exists in the **full** view — RFN's unfiltered graph holds 11 line-0 SCHEMA/structure edges (e.g. `temp_dqrq_bulk@128` → `IFX13@0`) and 7 line-0 chips; none of them survives the fold into the flow-only view.

**5d — claimed-together.**

*Example 1 — the join-key line is already claimed (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ❌ verified: this flow-only closure serves nothing at L41, so the join group earns no SECOND edge here — the group's own anchors are L95/L117/L150/L156, and the **full** view is what carries JOIN/join step @41. (The earlier text said "the podtao group" — a copy-paste from the `podtao` examples; the searched field here is `lending_ref`.)

  context: complete in the rows above.

*Example 2 — the line claimed by another field's read (EAST5, searching `org_no_cbrc`)*

- Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — ❌ (full view only: TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41`; `d.`'s line is claimed by `c`'s read — no extra fold edge)

The cited lines in their SQL (EAST5 L41 / L43 / L145, verbatim):

```sql
L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← `east5_stzfxxb@41`
L43:         SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh, --金融许可证号   ← the cited line
L145:        LEFT JOIN bdm_pub_branch c --机构信息表   ← `bdm_pub_branch@145` — the box whose read claims the line
```

**5e — no cross-statement instance duplication.**

*Example 1 — the occurrence stays with its own statement (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199`) (edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160`)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ sibling leg, dropped here (field-involvement rule 3b); the R46d emission that folded this occurrence onto the job-log instance (`bdm_acc_loan_info_sup@223`) is the canonical's point-23(a) NOT-PINNED refusal

The cited lines in their SQL (SUP_M L160→L202 and the job-log instance @223, verbatim):

```sql
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← `p2@199`
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← the searched field's own leg
L202:          AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD') -- 取前一天的数据   ← the sibling leg
L223:        bdm_acc_loan_info_sup   ← `bdm_acc_loan_info_sup@223` — the job-log instance the fold refuses
```

*Example 2 — the job-log statement's own instance (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — resolved by ruling 7-A: the log never writes this field — nothing shows (final state)

  context: complete in the rows above.

**5f — no foreign-owner guessed fold.**

*Example 1 — `T_BRANCH.data_dt` attributes to `T_BRANCH` (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250 — the occurrence's owner is `BDM_PUB_HSBC_ACCT_BRANCH` and `a` has no token on the line; the **full** view serves only the sibling chip's own SCHEMA/structure `T_BRANCH@250` → `data_dt@250`; canonical point 23(b): the two folded engine edges are NOT PINNED)

  context: complete in the rows above.

*Example 2 — attribution stays with the join owner (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199` — the fold stays with `p2@199`, never re-attributed to the searched compound without owner evidence)

  The cited lines in their SQL (L199→L201, verbatim):

```sql
L198:      loan_final p1
L199:      LEFT JOIN bdm_acc_loan_info_sup p2        ← the anchor + the fold's owner box
L200:      ON
L201:          p2.lending_ref = p1.lending_ref        ← cited by `lending_ref@201`: YOUR field is the join key
L202:          AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')
L203:          AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'
```

### §6 GATE (value-cone)

**6a — cross-table same-name seeds excluded.**

*Example 1 — `T_BRANCH.data_dt` cannot lend its closure (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250; the foreign same-name chip is excluded — canonical point 23(b) NOT PINNED)
- L251: `WHERE a.p_dt = '${load_date}' and a.rn='1';` — ❌ (no edge served @251 — `a.p_dt` is another field of another table; the **full** view carries `a`'s own FILTER/row selection and value-copy rows here, all excluded from this closure)

context: complete in the rows above.

*Example 2 — a line that carries no occurrence of the searched field at all (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — ❌ verified: no edge served @43 in this closure — the line carries no `p_dt` occurrence (its own fields are `c.org_no_cbrc`/`d.org_no_cbrc`, the same-NAME pair on two foreign boxes `bdm_pub_branch@145`/`@148`; the **full** view carries the NVL's rows here). The old text cited L42, which is a SQL comment line in the sample.
- L190: `WHERE p_dt = '$(load_date)'` — ✅ (edge: FILTER/filter step @190, `p_dt@41` → `east5_stzfxxb@41` — the searched table's own predicate, for contrast)

The cited lines in their SQL (EAST5 L41 / L43 / L145 / L148 / L190, verbatim):

```sql
L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← `east5_stzfxxb@41` / `p_dt@41`
L43:         SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh, --金融许可证号   ← the cited line
L145:        LEFT JOIN bdm_pub_branch c --机构信息表   ← `bdm_pub_branch@145`
L148:        LEFT JOIN bdm_pub_branch d --机构信息表   ← `bdm_pub_branch@148`
L190:        WHERE p_dt = '$(load_date)'   ← the searched field's own predicate
```

**6b — foreign statement trunks excluded.**

*Example 1 — the job-log trunk drops (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — ❌ (no edge served @211)
- L213: `'$(load_date)' AS data_dt` — ❌ (no edge served @213 — the statement writes only literals + COUNT(1): ⚡ 7-A shapes this)
- L223: `bdm_acc_loan_info_sup` — ❌ (no edge served @223 — the statement READS the searched table's output but the whole trunk drops)

The cited lines in their SQL (SUP_M L211→L213 and L222→L223, verbatim):

```sql
L211:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, …, STATUS, remarks)   ← (the row above)
L212:        SELECT   ← the SELECT head the trace skips
L213:        '$(load_date)' AS data_dt   ← (the row above)
L222:        FROM   ← the FROM the read side hangs on
L223:        bdm_acc_loan_info_sup   ← (the row above)
```

*Example 2 — a trunk the engine still serves IN ERROR (EAST5 × `p_dt`) — 7-A corollary violation, fix ledgered*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L179: `INSERT INTO TABLE rrcdm_job_log_exec_par( data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks )` — ❌ **ILLEGAL (7-A corollary violation)** — the edge `TABLE_FLOW/write leg @179, output@179 → rrcdm_job_log_exec_par@179` IS served today, but the column list writes `data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks` — **never `p_dt`** — and the SELECT feeds only literals + `COUNT(1)` + `getdate()`. The served edge is the log's own frame→write trunk, admitted through the carrier-is-None skeleton fallback (`_hop_carrier` returns None on the @179 frame, so the involvement filter never sees a sibling chip to refuse); the carried evidence proves it — the reason's own segment is `‖⟐ output@L179 → rrcdm_job_log_exec_par@L179‖` and `p_dt` appears only in the carried prefix `p_dt@L190 → east5_stzfxxb@L189`. Fix ledgered (suspended F3 item: test the edge's own carried segment, not its display endpoints).
- L189: `FROM EAST5_STZFXXB` — ❌ (same trunk, same defect: the log's read-side chain `east5_stzfxxb@41 → output@179` + the table-level `REF/read @189` are served under the identical fallback)
- L190: `WHERE p_dt = '$(load_date)'` — genuine `p_dt` occurrence (2d: the predicate exists and filters the log's read), **but** per 7-A's corollary the statement contributes nothing to `p_dt`'s closure because its write never carries `p_dt` — the trunk legs that predicate feeds (@179, @189 chain into `rrcdm_job_log_exec_par`) must drop; the FILTER row's final rendering is part of the same suspended fix.

*Note (corrected 2026-09-02 — the earlier note here was factually wrong):* the earlier text claimed "EAST5's trunk is served because the searched `p_dt` IS a column the log writes". **The L179 column list contains no `p_dt`** — the log writes `data_dt` + literals + `COUNT(1)`. Under §7-A's corollary the correct state is: the log contributes NOTHING to `p_dt`'s closure. What IS the rule working: PL's trunk (@253/@254) for `data_dt` — `data_dt` genuinely IS a written column there. SUP_M (searching `lending_ref`) and DL (@549, `lending_ref`) drop for the same corollary. The EAST5 residual is the suspended F3 defect (carrier-is-None skeleton admission + the compound fold hiding the sibling identity), not a rule gap.

**6c — foreign-owner folds respected.**

*Example 1 — the gate never re-parents (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250 — the edge's owner stays `T_BRANCH`; the searched compound is never handed it without owner evidence)

  context: complete in the rows above.

*Example 2 — the fold stays with its own owner (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199`; edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160` — the fold stays with `p2@199`, never re-attributed to the searched compound without owner evidence)

The cited lines in their SQL (SUP_M L160→L201, verbatim):

```sql
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L198:        loan_final p1
L199:        LEFT JOIN bdm_acc_loan_info_sup p2 -- 贷款借据信息附属表   ← the cited line
L200:        ON
L201:          p2.lending_ref = p1.lending_ref -- p1表和p2表贷款借据编码相等   ← `lending_ref@201`
```


**6d — alias/feeder-box scope (landed 2026-09-02, the carrier fix).**

*Example 1 — an alias enters only while the searched field's expression reads through it (EAST5 × `BBZ`)*

- Search field: `east5_stzfxxb.BBZ` (script: EAST5_STZFXXB_M.sql — verified by live build: 10 edges / 6 nodes)
- L141: `FROM bdm_acc_entrusted_payment a` — ✅ (edge: ALIAS/chain @141, `bdm_acc_entrusted_payment@141` → `a@141`) (edge: TABLE_FLOW/chain @141, `a@141` → `output@41` — BBZ's arm conditions read `a.charge_department` / `a.TAG_PRIMARY_ACCOUNTABLE_PARTY` THROUGH this alias: it is a feeder box)
- L151: `LEFT JOIN BDM_ACC_INTERNAL_COUNTERPARTY e` — ❌ (no edges served — `e.acct_no` feeds `stzfdxzh`@53 only, never BBZ; the served chips `e@152`/`f@155` and their chains drop with it)
- L154: `LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f` — ❌ (no edges served — `f.df_dfzh/df_dfhm` feed `stzfdx*` only)

*Example 2 — the feeder alias STAYS (same closure)*

- L141: `FROM bdm_acc_entrusted_payment a` — ✅ (edge: ALIAS/chain @141, `bdm_acc_entrusted_payment@141` → `a@141`) (edge: TABLE_FLOW/chain @141, `a@141` → `output@41` — BBZ's arm conditions read `a.charge_department` / `a.TAG_PRIMARY_ACCOUNTABLE_PARTY` / `a.remark` THROUGH this alias: it is a feeder box, so the alias hop and the row chain stay as skeleton)

*Example 3 — the non-feeder aliases DROP (same closure)*

- L151: `LEFT JOIN BDM_ACC_INTERNAL_COUNTERPARTY e` — ❌ (no edges served — `e.acct_no` feeds `stzfdxzh`@53 only, never BBZ; the served chips `e@152`/`f@155` and their chains drop with it)
- L154: `LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f` — ❌ (no edges served — `f.df_dfzh/df_dfhm` feed `stzfdx*` only)

The cited lines in their SQL (EAST5 L141 → L155, verbatim):

```sql
L141:  FROM bdm_acc_entrusted_payment a   ← a feeder: BBZ's arms read a.* through it — STAYS
L151:  LEFT JOIN BDM_ACC_INTERNAL_COUNTERPARTY e   ← feeds `stzfdxzh` only — DROPS with its chain
L154:  LEFT JOIN v_bdm_sys_ftpsje_jydsf('$(load_date)') f   ← feeds `stzfdx*` only — DROPS with its chain
```

context: complete in the rows above.

**6e — own-segment rule (landed 2026-09-02, the carrier fix).**

*Example 1 — a sibling's trunk leg drops even when its endpoints render as the searched table (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql — verified by live build)
- L179: `INSERT INTO TABLE rrcdm_job_log_exec_par( data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks )` — ❌ no edge (the job-log writes `data_dt` + literals + `COUNT(1)` — never `p_dt`; the old trunk `‖⟐ output@L179 → rrcdm_job_log_exec_par@L179‖` drops: its own carried segment is not `p_dt`'s participation — 7-A corollary)
- L189: `FROM EAST5_STZFXXB` — ✅ (edge: REF/read @189, `p_dt@190` → `east5_stzfxxb@189` — carried segment `‖p_dt@L190 → east5_stzfxxb@L189‖`: the read the @190 predicate filters)
- L190: `WHERE p_dt = '$(load_date)'` — ✅ (edge: FILTER/field flow @190, `p_dt@190` → `east5_stzfxxb@189` — carried segment `‖p_dt@L190 → east5_stzfxxb@L189‖`: the searched field's own row selection)

*Example 2 — the legal-stay contrast: the searched field's OWN write trunk (same closure)*

- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ the @41 write legs STAY — 3 edges (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`); there is NO own-membership edge here (7-A rule 1: `p_dt` IS a column this INSERT writes). The 6e test is what separates this trunk (the searched field is written here → stays) from the job-log trunk @179 (the searched field is not written there → drops).

The cited lines in their SQL (EAST5 L179 → L190, head and tail, verbatim):

```sql
L179:  INSERT INTO TABLE rrcdm_job_log_exec_par( data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks )   ← no `p_dt` in the column list — the trunk DROPS (6e + 7-A corollary)
L185:  ,COUNT(1) AS total_rows   ← the SELECT feeds only literals + a count
L189:  FROM EAST5_STZFXXB   ← the read the trunk's source frame carries — the @190 filter is `p_dt`'s only role here
L190:  WHERE p_dt = '$(load_date)'   ← the searched field's own row selection — STAYS (2d)
```

context: complete in the rows above.


---

## ⚡ 7. THE RULING ITEMS — where the rules conflict

### ⚡ 7-A. The job-log continuation (R29 vs the field-involvement rule) — ✅ RESOLVED 2026-09-01 (ruled: write leg only)

```sql
L155:  INSERT OVERWRITE TABLE bdm_acc_loan_info_sup ...   ← the value lands here ✅
L211:  INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, ...)
L212:  SELECT '$(load_date)' AS data_dt, COUNT(1) ...     ← the written value is a constant
L222:  FROM bdm_acc_loan_info_sup
```

> **RULED 2026-09-01 (USER RULING, boundary confirmed "write leg only") — the historical
> positions below are superseded.** The user's insight: `data_dt` IS a column of the
> write target, so this statement WRITES to the searched field — a write is the field's
> data flow even when the value is a constant. Three rules:
> (1) when the SEARCHED field is the column being written, its write edge SHOWS —
> `TABLE_FLOW ⟐output → rrcdm_job_log_exec_par @211`, a real highlight line;
> (2) "write leg only": the INSERT's OTHER literal columns (`object_domain`, `COUNT(1)`, …)
> stay OUT — they are siblings written with constants, and the 3a/chip-prune ruling drops
> them; the FROM-read does not drag the searched field's upstream into the statement;
> (3) corollary: a field the log does NOT write (`lending_ref`, `iiapty`, …) gets NOTHING
> from the statement — the old R29 "always continue through the log-write" behavior is
> RETIRED, and the ground-truth docs were repaired to this (`tools/GROUND_TRUTH_*.md`,
> user ruling cited in each).
>
> Measured at landing: the filter already served rule (1) — across all 20 jaccard cases
> the ONLY dropped write leg was a *sibling's* — so no engine change was needed; what
> changed is the corollary and the docs. Pinned by 6 tests in
> `test_field_involvement_rule.py` (`test_ruling_7a_write_leg_shows_for_the_written_column`
> and friends); the 2 former red R29 doc tests are GREEN and the release.sh deselect list
> is EMPTY. FSA's **76 false "consumed" claims** stay dead — none of those fields is the
> written column.
>
> **Historical positions (superseded):** R29 (2026-08-12) said SHOWN — "the graph must be
> one connected flow". The field-involvement reading said NOT shown — the log carries a
> count + literals. The measured inconsistency (EAST5/PL trunks shown; SUP_M/iiapty
> dropped) is resolved by rule (1)+(3): the trunk shows exactly and only for fields whose
> column the log writes.

### ⚡ 7-B. The own-table co-filter sibling (J12-20 pin) — ✅ RESOLVED 2026-09-01 (ruled: edge drops AND chip pruned)

PL @265: `AND charge_department = 'OPS_CLBS_PLoan'` — an edgeless co-filter sibling on the searched table's own compound. J12-20 pinned it as a documented closure member; the DL mirror serves it; but the PL **filtered** view drops it (a filtered-path under-emission). **(J2 fixing.)**

> **RULED 2026-09-01 (USER RULING, `backend/tests/jaccard_canonical.py` docstring point 26) — the
> paragraph above is HISTORICAL, the ruling reverses it.** Two rules: (1) the sibling belongs-to
> edge DROPS out of the flow-only closure — it is the sibling's own structural fact, not the
> searched field's flow (this also reverses point 21's "skeleton STAYS"); (2) an edge-less sibling
> chip is PRUNED from the flow view — "they are not contributing to the data flow. I think they
> should be removed." The **FULL view keeps everything** (verified 0 full-view diffs across the 32
> changed snapshot baselines). Landed as `l2_builder._apply_field_involvement` Class 3 +
> `_prune_orphan_sibling_chips` (`l2_builder.py:2506`, `:2618`); the canonical
> `charge_department@265` (pl↓PL) and `@561` (dl↓DL) entries are removed from `CANONICAL_NODES`;
> pinned by `test_j2_fold_ownership.py` ("Defect C, REVERSED 2026-09-01") and
> `test_field_involvement_rule.py::test_chip_prune_removes_only_orphan_siblings`. Gate after the
> ruling: **20/20 cases at 1.0000/1.0000**. The two J12-20 ground-truth doc rows still carrying
> the pre-ruling pin (`tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO.md` §8.6 and
> `tools/GROUND_TRUTH_BDM_ACC_LOAN_INFO_Digitallending.md` §8.5) still need the same repair
> (owner: docs).

**Example 1 — the co-filter on the searched table (PL × `data_dt`, real)**

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt` → `bdm_acc_loan_info`; edge: TABLE_FLOW chain @263 into the output frame)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER @264 — the SEARCHED field's own predicate, rule 2d; canonical F1)
- L265: `AND charge_department = 'OPS_CLBS_PLoan'` — ❌ (dropped — USER RULING 2026-09-01: the sibling's predicate is not `data_dt`'s flow, and the edge-less `charge_department@265` chip is pruned with it; canonical point 26 removed it from `CANONICAL_NODES`)

  context: complete in the rows above.

**Example 2 — the DL mirror (Digitallending × `data_dt`, real, verified)**

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_Digitallending.sql)
- L561: `AND charge_department = 'WPB_CDT_Digitallending'` — the mirror of PL @265: a co-filter by the same sibling on the searched table's own compound. Pre-ruling both PL and DL served the chip (and J12-20 treated the PL miss as a bug); post-ruling BOTH drop it — verified in the served closure (live build, 9 edges / 6 nodes @549/@550/@559/@560): **0 `charge_department` chips** in the flow view, no edge @561. The FULL view keeps the chip and its belongs-to (the "what else filters this box" answer lives there).

The cited lines in their SQL (DL L549→L561, verbatim):

```sql
L549:      INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, …, STATUS, remarks)   ← `@549` — the log's INSERT
L550:        SELECT '$(load_date)' AS data_dt   ← `@550` — the literal `data_dt` projection
L559:        FROM bdm_acc_loan_info   ← `@559`
L560:        WHERE data_dt = '$(load_date)'   ← `@560`
L561:        AND charge_department = 'WPB_CDT_Digitallending'   ← the cited sibling filter — dropped here
```

**What stays vs goes (both examples)**: the SEARCHED field's own predicate row lights (2d — L264's FILTER); a SIBLING's predicate row is invisible in the flow view — no edge, no chip. If a co-filtering column were itself the searched field (search `charge_department` on PL), L265 becomes ITS filter step and lights (2d) — the rule is about whose field it is, not about the clause.

### ⚡ 7-C. The sibling same-name REF edge (`src_b.dt` → `src_a.dt`'s closure) — ✅ RESOLVED (V7 g1, v3.3.195)

The extractor builds a same-name REF edge between two tables' same-named columns; the walker can ride it into the sibling's closure. Under the field-involvement principle this is other-field flow → the traversal excludes it. (The *edge* is a real extraction fact — the question was whether the *walker* traversed it. V7's g1 gate: it does not.)

**Example 1 — a JOIN builds the same-name pair (SUP_M × `lending_ref`, real)**

- Search field: `bdm_acc_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN key @156 ×2, `lending_ref` → `loan_final` — the two occurrence identities, LFS117 p6-side + LFS138 p1-side) — ✅ (the seed's OWN belongs-to @156 stays: `rollover_loan_info` → `lending_ref`, `bdm_acc_loan_info` → `lending_ref`)
- The same line also pairs `p6.lending_ref@156` with `p1.lending_ref@156` — a same-name REF pair. ❌ **NOT served**: any hop THROUGH that pair into `p6.lending_ref`'s own upstream (the `rollover_loan_info` producer chain). Verified in the served closure: no edge is sourced BY `p6.lending_ref@156`; the only `p6` edges are the searched field's own reads (`REF lending_ref → p6@155 @155` — the field's own read through the alias) and the skeleton.

The cited lines in their SQL (SUP_M L155→L156, verbatim):

```sql
L155:          LEFT JOIN rollover_loan_info p6   ← `p6@155` — the field's own read through the alias
L156:          ON p6.lending_ref = p1.lending_ref   ← the cited same-name pair
```

Read it as: the join key shows (2e); the join PARTNER's own life story does not.

**Example 2 — two sources, one column name (the G1 pinned fixture)**

`tests/test_g1_adjudicated_fixes.py` pins the adjudicated shape: two source relations `src_a`/`src_b` BOTH project a column `dt` (and a key `k` joins them). Searching `src_a.dt`:

- Pre-V7 (the defect): the same-name ride-through served `dt@7` and `src_b@7` — the JOIN PARTNER's occurrence and its frame — dragging `src_b`'s side of the story into `src_a.dt`'s closure.
- Landed: `dt@7`, `src_b@7`, `⟐s2@7` are OUT; the searched source's own `s1@6` + `s1.dt@5` are restored; `k` stays out. Pinned by `test_g1_adjudicated_fixes.py` (24 tests).

  context: the lines cited here (`s1.dt@5`, `s1@6`, `dt@7`, `src_b@7`, `⟐s2@7`) belong to the pinned fixture in `tests/test_g1_adjudicated_fixes.py`, not to a `samples/sql_sample_v1/` script.

Boundary: the JOIN edge ITSELF between the two same-name columns is a real extraction fact and stays in the FULL view — 7-C only rules that the flow-only walker does not traverse it as a path into the partner.

### ⚡ 7-D. The ⟐output membership edges of sibling chips — ✅ SUPERSEDED (J1 Class 2 + point 26; determinism landed via V8, v3.3.197)

When a sibling chip is admitted (co-written projection), its ⟐output membership SCHEMA edge rides along. J1's rule drops sibling VALUE edges but keeps sibling belongs-to/membership — the exact boundary needs the value-cone ruling (the full R-GATE, v3.3.195).

**RESOLUTION — no separate ruling was ever needed, because later rulings subsumed it:**
point 26 rule 1 (the 3a reversal) drops a SIBLING's belongs-to/membership from the flow-only
closure, and the chip prune removes the edge-less chips this leaves. So for the flow view the
answer is: **a sibling's ⟐output membership edge NEVER shows** (it is the sibling's own flow —
J1 Class 2 even before point 26); only a membership edge OF THE SEARCHED FIELD's own chip shows.
The FULL view keeps all of it. (The historical "BLOCKS the determinism fix" note below is also
overtaken: the determinism landing shipped in v3.3.197 via the V8 walker-order fix — the real
defect was the walk's DML admission order, not this boundary.)

**Example 1 — the surviving sibling's membership is still dropped (SUP_M × `lending_ref`, real)**

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ✅ (edge: COMPUTED @82, `lending_ref` → `reserved_field8` — the searched field feeds the sibling; this one edge is the chip's ONLY anchor)
- The same sibling's ⟐output membership — ❌ dropped: `output@160` → `reserved_field8` (SCHEMA) is not served in the flow view, though the **FULL** view carries it. Same for the write-chain legs (`reserved_field8@183` → `output@160`, the L183 write-projection read) — dropped by 3b.

The cited lines in their SQL (SUP_M L82 / L160 / L183, verbatim):

```sql
L82:         ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8   ← (the row above)
L160:      INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   ← `output@160`
L183:        ,p1.reserved_field8 AS reserved_field8 -- rollover业务标识（修改到期日期）   ← `reserved_field8@183` — the write-projection read leg
```

**Example 2 — the co-written partition sibling (EAST5 × `p_dt`)**

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ `p_dt`'s own write (2g/7-A: the searched column's slot, literal value)
- Sibling `charge_department`'s routing into the same output frame — ❌ dropped: its feeding CASE @51 and its output-frame membership/routing are `charge_department`'s own flow (3b), and its edge-less chips are pruned (3c/point 26). The **FULL** view shows the whole co-write.

The cited lines in their SQL (EAST5 L41 / L51, verbatim):

```sql
L41:       INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)   ← (the row above)
L51:         CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)   ← `@51` — the sibling's feeding CASE
```

**One-sentence summary**: a sibling's ⟐output membership is like the sibling's belongs-to —
structure of the TARGET, story of the SIBLING — so it shows only in the full view, and only
the searched field's own membership shows in the flow view.

---

# Summary — the decision tree

```
Is the edge about the SEARCHED field's VALUE?
├── YES → shown (read/write/compute/filter/join-key/group-key/window-key/
│         occurrence twin/AND-leg, each at its own line). A producer edge
│         anchors INSIDE the searched field's own producing expression —
│         the CASE arm — never at a sibling column's birth line (rule 4e)
├── Is it STRUCTURAL SKELETON → shown as context ONLY while it is the searched
│   field's OWN: headers, containers, the searched field's belongs-to, and an
│   alias/feeder box the searched field's expression reads through (6d).
│   A SIBLING's belongs-to DROPS (3a), an edge whose OWN carried segment is
│   not the field's participation DROPS (6e), and a box left with no edge is
│   pruned (3c extended to boxes)
├── Is it ANOTHER FIELD's value flow → dropped (the field-involvement rule)
├── Is it a statement that only NAMES the field but writes literals
│   (the job-log writes data_dt) → ✅ its write leg shows (RULING 7-A,
│   2026-09-01); fields the log does NOT write get nothing
└── Is it a same-name chip on another table → not seeded (RC-A, fixed)
```

# Rules provenance (which team/change landed which rule)

| Rule group | Landed in | By |
|---|---|---|
| Seeds (W1 + #399 alias expansion) | lineage.py W1 | R29/#399 |
| Value edges (FIELD_LAND/D2/W2-W6b) | lineage.py | R18–R44 |
| Occurrence twins (families 1-3) | variable_extractor_v2 (.9-.12) | R44/R45/G7 |
| JOIN-ON AND-legs + Phase 9 | dependency_graph (.12) | F-E1/V5 |
| Multi-anchor fold + Fix H + line-0 + LFS108 | l2_builder `_combine_edges` | G8/AD2/J2 |
| Field-involvement admission (sibling value legs drop) | l2_builder `_apply_field_involvement` | J1 (#48) |
| R-GATE value-cone + recall guard + bare-column seeds | lineage `_VALUE_CONE_GATE`/`_OWNERLESS_SEED` | V4/AD3/FSC |
| is_target scoping (searched entities ∪ receiving write targets) | l2_builder `_scope_target_stamp` | R46a/AD3 |
| Casing invariance (`_fold`, 3 engines) | lineage/l1_builder/dataflow_service | H7/R46e |
| Model persistence beside graph cache | graph_service `model_{key}.json` | V6/FSC-2 |
| Own-segment classification + alias/feeder-box scope (6d/6e) | l2_builder `_apply_field_involvement` | SEGMENT, 2026-09-02 |
| Provenance-linked AS-alias routing (2h) | l2_builder `_apply_field_involvement` own-frames admission | F1F2, 2026-09-02 |
| Producer-occurrence anchoring (4e) | dependency_graph Phase 9b + extractor family 5 (`8c5c6a4`, v3.3.199) | 4E, 2026-09-02 (landed) |
