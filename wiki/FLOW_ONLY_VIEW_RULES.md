# Flow-only view: the complete edge show/hide rules

> Every rule that decides whether an edge appears in the L2 flow-only view, with examples
> from the flagship scripts, and the confusing ones labeled. Written 2026-09-01 for the
> user's review; the two ⚡ ruling items gate the jaccard benchmark's final state.

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
| 2c | **Computes**: the value inside an expression feeding an output | ✅ | `CONCAT(p2.poctcd, ...) = p1.lending_ref` @41 |
| 2d | **Filters on the field**: a predicate selecting rows by it | ✅ | `WHERE p1.data_dt = '$(load_date)'` |
| 2e | **Join keys on the field**: the join operand IS the field | ✅ | `ON p6.lending_ref = p1.lending_ref` @156 |
| 2f | **Group/window keys on the field**: it decides grouping/ranking | ✅ | `GROUP BY ... product` @246; `ROW_NUMBER() OVER(PARTITION BY p1.acnw)` @64 — the **Reappears** stage |
| 2g | A statement writes the SEARCHED field's column with a **literal/constant** value | ✅ (write leg only — USER RULING 2026-09-01, resolving 7-A) | The job-log: `INSERT INTO rrcdm_job_log_exec_par(data_dt, ...) SELECT '$(load_date)' AS data_dt, COUNT(1)...` — searching `data_dt`, its write edge @211 shows even though the value is a constant; the INSERT's other literal columns stay out |

---

## 3. SIBLING rules — other fields written by the same statement

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

*Note:* the `reserved_field8` **chip itself** survives — the seed's own COMPUTED edge feeds it at L82 (the CASE that computes `reserved_field8` READS `lending_ref`), so the confirmed prune keeps it: it is edge-anchored by the searched field's own flow, not by its belongs-to. The rest of this closure (L9/13/16/19/22/26/29/50/52/59/64/67/82/84/95/117/150/155/156/160/163/198/199/201, 51 edges) is untouched — only the sibling's own rows went.

Read the picture as: "`reserved_field8` appears because YOUR value flows
into it" — never "…and it also exists on this box" (that fact is a
full-view fact now).

**Example 2 — co-filter sibling (PL × `data_dt`)**

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L263: `FROM bdm_acc_loan_info` — (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`; canonical F1)
- L265: `AND charge_department = 'OPS_CLBS_PLoan';` — (dropped — USER RULING 2026-09-01: no edge served here and the edge-less `charge_department@265` chip pruned with it — canonical point 26: the J12-20 doc row is repaired out of `CANONICAL_NODES`)

*Note:* the searched field's own predicate @264 is untouched (2d). This is the row J12-20 pinned and the **resolved** §7-B — resolved then by ADDING the chip; the belongs-to that anchored it is now dropped, and the edge-less chip removed, by this ruling. (The old text wrote the predicate as `p1.data_dt` — the sample line has no `p1.` prefix.)

**Example 3 — dynamic-partition co-write (EAST5 × `p_dt`)**

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (dropped — USER RULING 2026-09-01: the sibling `CHARGE_DEPARTMENT@41` belongs-to edges the **full** view serves here — `east5_stzfxxb@41` → `CHARGE_DEPARTMENT@41` and `output@41` → `CHARGE_DEPARTMENT@41` ×2)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — field-involvement rule 3b: the feeding expression, and the sibling belongs-to SCHEMA/structure @51 `a@141` → `charge_department@51` the **full** view carries)

*Note:* L41 is `p_dt`'s own write (a literal partition value — rule 2g); the same PARTITION clause co-writes `charge_department` as a DYNAMIC partition. This is the shape that motivated the ruling: write-heavy statements co-write dozens of columns, and under the old rule every one of them dragged a chip + belongs-to edge into the closure.

**One-sentence summary for all three**: the searched field's closure
shows only what the searched field's own value drives — a sibling has no
edges and no edge-less chips in it. "What else is written on this line /
this box" is a question for the full view.

### Worked examples — the other rule groups

Three complete cases per group, same convention as §3a: the searched
field first, then one row per SQL line with the edges the engine
actually serves there (payload-checked against
`backend/tests/snapshots/`), shown (✅) vs dropped (❌).

**§1 SEEDS — where the closure starts**

1. *1a, own-table occurrence*: search `lending_ref` → every `p1.lending_ref`
   chip on the `bdm_acc_loan_info` compounds seeds. ✅
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L13: `lending_ref` — ✅ (edge: SCHEMA/structure @13, `rollover_loan_info@9` → `lending_ref@13`) (edge: REF/value copy @13, `lending_ref@13` → `lending_ref@82`)

   *Note:* the seed's own occurrences are the closure's first lit lines; L82's NVL read is lit by the same value copy.

2. *1b, alias expansion (#399)*: `FROM v_bdm_customer_all('...') a`,
   search the TVF's `cust_no` → the alias's owning entities seed. ✅
    - Search field: `ods_gdc_split_fg_rating_temp.cust_no` — the snapshot seed, whose closure carries the TVF-alias form `a.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
    - L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: TABLE_FLOW/chain (read into output) @1103, `a@1103` → `output(exists13)@1103`) (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`) (edge: REF/read @1103, `cust_no@1105` → `a@1103`)
    - L1104: `LEFT JOIN bdm_acc_deposit_acct b` — ✅ (edge: ALIAS/chain (alias hop) @1104, `bdm_acc_deposit_acct@1104` → `b@1104`) (edge: REF/read @1104, `cust_no@1105` → `b@1104`)
    - L1105: `ON a.cust_no = b.cust_no` — ✅ (edge: JOIN/join step @1105, `cust_no@1105` → `output(exists13)@1103` — served twice, one per side of the predicate) (edge: SCHEMA/structure @1105, `a@1103` / `b@1104` / `b@1111` → `cust_no@1105` ×3) (edge: COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`)

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

   *Note:* this was the R-GATE's fix — same name, different table, no seed.

**§2 VALUE — edges that carry the field's value**

1. *2d, filter*: `WHERE data_dt = '${load_date}'` → the predicate edge on
   the searched compound shows; the highlight lands on the WHERE line.
    - Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
    - L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
    - L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`)

   *Note:* the highlight lands on the WHERE line, not on the box.

2. *2e, join key*: `ON p6.lending_ref = p1.lending_ref` @156 → the JOIN
   edge shows at the join's own line (and ONLY there — a join edge
   anchored at a projection line is the Class-1 defect, dropped).
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
    - L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156, `lending_ref@13` → `loan_final@64` — the p1 side) (edge: JOIN/join step @156, `lending_ref@82` → `loan_final@64` — the p6 side, canonical LFS138) (edge: SCHEMA/structure @156, `bdm_acc_loan_info@16` → `lending_ref@13`) (edge: SCHEMA/structure @156, `rollover_loan_info@9` → `lending_ref@82`)
    - L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ❌ no JOIN edge here (a projection line; it serves the seed's own COMPUTED/compute step `lending_ref@82` → `reserved_field8@82` instead)

   *Note:* both sides of the predicate light at the join's own line — never at a projection line.

3. *2g, name-but-no-value*: the job-log `INSERT INTO rrcdm_job_log_exec_par(...) SELECT '$(load_date)' AS data_dt` writes a column NAMED like the field but the value is a literal — ✅ **resolved by ruling 7-A (write leg only, 2026-09-01)**: searching `data_dt`, its write edge shows (see §7-A).
    - Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
    - L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ ruling 7-A (write leg only, 2026-09-01): shown — (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253` — canonical P16)
    - L254: `SELECT '${load_date}' AS data_dt,` — ✅ ruling 7-A: shown — (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253` — canonical V2) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254` — canonical M1)

   *Note:* the engine serves this trunk here — and in EAST5 (@179/@180) — while SUP_M's identical job-log trunk (@211/@213) drops. That inconsistency IS ruling 7-A.

**§4 TWINS — the same field at many lines**

1. *4a, per-occurrence lines*: `charge_department`'s CASE arms light
   exactly at {54, 55, 56, 66, 68, 70} — each occurrence at its own line,
   never one merged blob. *(not a snapshot seed — the lit set is the doc's
   own audit record, not payload-checkable here)*
    - Search field: `east5_stzfxxb.charge_department` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; no payload to check against)
    - L54: `CASE WHEN a.CHARGE_DEPARTMENT ="GTRF_CoreTrade_SCSAI" THEN a.entd_opp_acct_name`
    - L55: `WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_acct_name,f.df_dfhm)`
    - L56: `WHEN a.charge_department = "OPS_MBS" THEN REGEXP_REPLACE(`
    - L66: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_no,f.df_dfxh)`
    - L68: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_name,f.df_dfxm)`
    - L70: `CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark`

   *Note:* the audited lit set is {54,55,56,66,68,70}; the SQL text carries a `charge_department` occurrence at L51 as well (the arm the audited set does not count).

2. *4b, JOIN-ON AND-legs*: continuation legs of one JOIN get their own
   occurrence twins, so the highlight reaches the AND lines.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
    - L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served here in this closure (`data_dt` is a sibling field: its leg is dropped by the field-involvement rule 3b; the **full** view carries the JOIN/join step `bdm_acc_loan_info_sup@160` → `output@160` @202 that this closure excludes)
    - L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ nothing served here (same sibling drop; the **full** view carries the JOIN/join step @203)
    - L224 (PL): `AND a.p_dt = c.p_dt` — *(script: BDM_ACC_LOAN_INFO_PL.sql; not a snapshot seed for `p_dt` — no payload to check against)*

   *Note:* each leg of the searched field's own JOIN anchors its own line; a sibling leg's line stays dark in the searched field's closure.

3. *4d, no owner evidence*: `d.org_no_cbrc` @43 — the line's owner is
   already served by `c`'s NVL read; no duplicate twin is minted. ❌ No
   extra edge, no double highlight.
    - Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; the FULL-view rows below are what the flow-only view refuses to duplicate)
    - L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — (edge: SCHEMA/structure @43, `c@145` → `org_no_cbrc@43` and `d@148` → `org_no_cbrc@43` — **full view only**) (edge: TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41` — **full view only**)

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

   *Note:* one edge per occurrence line — no merged blob.

2. *5b, keeper-line*: among carriers of one group, the one standing on
   the chip's own line wins the fold (Fix H) — the served edge's anchor
   is the line you'd click.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
    - L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198`)

   *Note:* the chip's own line (@163) carries its belongs-to; the read that consumes it anchors at the instance's line (@198), never at a projection line.

3. *5d, claimed-together*: the LFS108 NOT-IN filter — a group whose line
   another relationship already claims earns no second edge. ❌ One
   story per line.
    - Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
    - L48: `AND p1.lending_ref NOT IN (` — ❌ no second edge served @48 (canonical row LFS108 stays LIVE as `FILTER lending_ref@13` → `⟐subq@0` anchor 48, but the served closure carries nothing here — the L41 join carrier already claims this story)
    - L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ the line the flow-only closure leaves dark: no edge at all in this closure (the **full** view serves JOIN/join step @41)

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
| 4a | Each occurrence lights at its **own line** | ✅ | EAST5 `charge_department`'s CASE arms (L51/55/56/66/68/70): lit at exactly {54,55,56,66,68,70} |
| 4b | **JOIN-ON AND-continuation legs** (family-4 twins) | ✅ | SUP_M L201-203: `p2.lending_ref = p1.lending_ref` @201, `AND p2.data_dt = DATEADD(...)` @202, `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` @203 — each leg anchors its own line; PL L221 `AND c.p_dt = '${load_date}'` |
| 4c | A line already anchored by a surviving var — no duplicate | ❌ | The L82 NVL read: anchored once |
| 4d | A twin with **no owner evidence** is not minted | ❌ | EAST5 L42: `d.org_no_cbrc` inside `NVL(c.org_no_cbrc,d.org_no_cbrc)` — a bare occurrence with no clause owner of its own earns no twin (the paren-scope owner rule) |

---

## 5. FOLD rules — which carrier represents the group

| # | Rule | Shown? | Example |
|---|---|---|---|
| 5a | **Multi-anchor**: N occurrences joining the same target at N lines → N edges | ✅ | SUP_M: `lending_ref` anchors THREE join sites at three lines — L41 (`CONCAT(...)=p1.lending_ref`), L156 (`ON p6.lending_ref = p1.lending_ref`), L201 (`p2.lending_ref = p1.lending_ref`) → 3 JOIN edges **(RC-B, fixed)** |
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
| 6b | **Foreign statement trunks**: a statement that doesn't carry the field's value doesn't enter | ❌ | The job-log DML trunk drops from `lending_ref`'s closure; `rrcdm ↓ EAST5` stays 3/3 |
| 6c | **Foreign-owner folds** respected | ❌ | PL @250: edges attribute to `T_BRANCH`, never the searched compound — **(J2 fixing)** |

---

## Rule-by-rule: two real examples + script segments for every item (1a–6c)

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

*Note:* the projection occurrence seeds the closure; the IN-predicate line lights with it (canonical LFS107).

*Example 2 — the partition-key occurrence seeds (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`)

*Note:* the INSERT's own PARTITION key occurrence is the seed; the whole closure for this script is these 7 edges (@41/179/189/190).

**1b — alias/TVF expansion (#399).**

*Example 1 — the TVF form, payload-verified (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` — the snapshot seed; the TVF-alias form `a.cust_no` sits inside this closure (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: TABLE_FLOW/chain (read into output) @1103, `a@1103` → `output(exists13)@1103`) (edge: TABLE_FLOW/chain (VT chain) @1103, `output(exists13)@1103` → `output@867`) (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`) (edge: REF/read @1103, `cust_no@1105` → `a@1103`)
- L1104: `LEFT JOIN bdm_acc_deposit_acct b` — ✅ (edge: ALIAS/chain (alias hop) @1104, `bdm_acc_deposit_acct@1104` → `b@1104`) (edge: REF/read @1104, `cust_no@1105` → `b@1104`)
- L1105: `ON a.cust_no = b.cust_no` — ✅ (edge: JOIN/join step @1105 ×2, `cust_no@1105` → `output(exists13)@1103` — one per predicate side) (edge: SCHEMA/structure @1105, `a@1103` / `b@1104` / `b@1111` → `cust_no@1105`) (edge: COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`)

*Note:* the TVF box `v_bdm_customer_all@1103` and its alias `a@1103` both enter the closure — the alias's owning entities seed (#399).

*Example 2 — the plain alias-qualified form (RFN, the FSC-2 case)*

- Search field: `a.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql — not a snapshot seed; no payload to check against)
- L1105: `ON a.cust_no = b.cust_no` — (edge: not verified against payload — line cited from SQL only)

*Note:* the doc's own record stands: before the model-persistence fix this seed was LOST (`search_matched: false`, the whole 1053-node graph served — the RFN **full** view is exactly those 1053 nodes / 6760 edges); after it the 40-node / 82-edge flow-only closure serves.

**1c — cross-table same-name does NOT seed.**

*Example 1 — the sup self-join leg SEEDS (that is 2e, not 1c)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ `p2` IS the searched table's sup instance (edge: REF/read @199, `lending_ref@201` → `p2@199`) (edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160`)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served @202 in this closure (`lending_ref` is the seed here, so the sibling leg drops; the **full** view carries SCHEMA/structure `p2@199` → `data_dt@160`, reason `‖p2.data_dt@L202‖`, plus the JOIN/join step `bdm_acc_loan_info_sup@160` → `output@160`)

*Example 2 — the foreign same-name column does NOT seed (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L221: `LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'` — ❌ (no edge served @221 — `c.p_dt` is a same-NAME, different-TABLE column of `ODS_CUPD_PLOAN_APS_CREDINF5`; the **full** view carries only that sibling chip's own SCHEMA/structure `c@221` → `p_dt@221` here)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19` — the searched table's own occurrence, for contrast)

### §2 VALUE

**2a — reads.**

*Example 1 — the SELECT-projection read (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
- L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198`)

*Note:* the projection occurrence lights at its own line (@163); the read that consumes it lands on the instance line (@198).

*Example 2 — the read that births the output column (DL × `lending_ref`)*

- Search field: `temp_kmbh_gl.lending_ref` (script: BDM_ACC_LOAN_INFO_Digitallending.sql)
- L99: `INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)',CHARGE_DEPARTMENT='WPB_CDT_Digitallending')` — ✅ (edge: TABLE_FLOW/write leg @99, `output@99` → `bdm_acc_loan_info@99`)
- L101: `A.acctnbr AS LENDING_REF` — ✅ (edge: TABLE_FLOW/write value @101, `LENDING_REF@101` → `output@99`) (edge: SCHEMA/structure @101 ×2, `output@99` → `LENDING_REF@101`) (edge: REF/read @426, `LENDING_REF@101` → `ods_ccb_cb_loan_acctloan@426` — the read that feeds this write)

*Note:* the old text cited "L100-101"; the INSERT is L99 and `SELECT` is L100 (which serves nothing). Canonical LFD3 pins the naming rule: no column list, so the SELECT alias IS the output column's name.

**2b — writes.**

*Example 1 — the value lands in the write target (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
- L160: `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)` — ✅ (edge: TABLE_FLOW/write leg @160, `output@160` → `bdm_acc_loan_info_sup@160`) (edge: ALIAS/chain (alias hop) @160, `bdm_acc_loan_info_sup@160` → `p2@199`)

*Note:* the write leg is the searched field's own — the statement's INSERT edge is admitted because `lending_ref` is written into the target.

*Example 2 — the partition slot write (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — ✅ (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`)

**2c — computes.**

*Example 1 — the field inside a join-key expression (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — (edge: not verified against payload — line cited from SQL only; this flow-only closure serves nothing at L41, while the **full** view carries JOIN/field flow (join step) @41, `bdm_acc_loan_info@16` → `p2@40`, reason `‖p1.lending_ref@L41 → CONCAT(…)‖`)

*Note:* the main table's "@41" citation is a full-view fact; the served flow-only closure for `lending_ref` lights the same expression's *sibling* JOIN site at L117 instead.

*Example 2 — a CASE mask computes the field (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1117: `OR (regexp_instr(A.LOAN_IN_ACCT_NAME,'[A-Za-z]+$') >= 1 AND length(A.LOAN_IN_ACCT_NAME) <> lengthb(A.LOAN_IN_ACCT_NAME))` — (edge: not verified against payload — line cited from SQL only)
- L1118: `THEN 'NI'` — (edge: not verified against payload — line cited from SQL only)
- L1119: `END AS DM_FLAG2` — (edge: not verified against payload — line cited from SQL only)

*Note:* the same shape IS payload-visible one script over: RFN's own closure serves COMPUTED/compute step @1105, `cust_no@1105` → `DM_FLAG2@1119`, and again @1178 — the audited written-768 step of the doc's record.

**2d — filters.**

*Example 1 — the searched field's own predicate (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19` — canonical F1)
- L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)

*Example 2 — its own predicate arm at its own line (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a snapshot seed; no payload to check against)
- L37: `AND podtao <> pofddt` — (edge: not verified against payload — line cited from SQL only)

**2e — join keys.**

*Example 1 — the field IS the join operand (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L155: `LEFT JOIN rollover_loan_info p6` — ✅ (edge: REF/read @155, `lending_ref@82` → `p6@155`) (edge: TABLE_FLOW/chain (CTE chain) @155, `p6@155` → `loan_final@64`)
- L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156, `lending_ref@13` → `loan_final@64`) (edge: JOIN/join step @156, `lending_ref@82` → `loan_final@64`)

*Example 2 — the operand edge at the join line (PL, searching `acnw`)*

- Search field: `ODS_CUPD_PLOAN_ACCTM_NEW5.acnw` (script: BDM_ACC_LOAN_INFO_PL.sql — not a snapshot seed; no payload to check against)
- L221: `LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'` — (edge: not verified against payload — line cited from SQL only; the **full** view of this script does serve JOIN/field flow (join step) @221, `ODS_CUPD_PLOAN_APS_CREDINF5@221` → `output@19`, reason `‖c.sxxyh@L221 → ⟐ output@L19‖`, i.e. the *sxxyh* operand, not `acnw`)

**2f — group/window keys.**

*Example 1 — the group key decides grouping (PL, searching `product`)*

- Search field: `bdm_fin_lrr_key_base_info.product` (script: BDM_ACC_LOAN_INFO_PL.sql — not a snapshot seed; the lit set is the doc's own audit record)
- L243: `group by arrangement_local_number,` — (edge: not verified against payload — line cited from SQL only)
- L244: `cb_pointer,` — (edge: not verified against payload — line cited from SQL only)
- L245: `account,` — (edge: not verified against payload — line cited from SQL only)
- L246: `product,` — (edge: not verified against payload — line cited from SQL only; the **full** view serves the sibling chip's belongs-to SCHEMA/structure @246, `bdm_fin_lrr_key_base_info@234` → `product@232` — the audited Reappears anchor)
- L247: `lrr_key) km1` — (edge: not verified against payload — line cited from SQL only)

*Example 2 — the window PARTITION key (DL, searching `acnw`)*

- Search field: `ODS_CUPD_CLD_ACCTMASTER_NEW.acnw` (script: BDM_ACC_LOAN_INFO_Digitallending.sql — not a snapshot seed; no payload to check against)
- L64: `,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN` — (edge: not verified against payload — line cited from SQL only)

**2g — named-but-literal write (✅ resolved by ruling 7-A, 2026-09-01).**

*Example 1 — the job-log data_dt (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — resolved by ruling 7-A (2026-09-01): the log never writes this field, so NOTHING shows — final state (no edge served @211)
- L212: `SELECT` — resolved by ruling 7-A: nothing shows (final state)
- L213: `'$(load_date)' AS data_dt` — resolved by ruling 7-A: nothing shows (final state)

*Example 2 — the same shape the engine DOES serve (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ ruling 7-A (write leg only, 2026-09-01): shown — (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253` — canonical P16)
- L254: `SELECT '${load_date}' AS data_dt,` — ✅ ruling 7-A: shown — (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253` — canonical V2) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254` — canonical M1)

*Note:* the two examples are the ruling's own contradiction — byte-identical job-log statements, one trunk dropped (SUP_M), one served (PL, and EAST5 @179/@180). ⚡ 7-A decides which is right.

### §3 SIBLINGS (post-ruling)

**3a — sibling belongs-to (dropped by the 2026-09-01 ruling).**

*Example 1 — `reserved_field8` is BORN on `lending_ref`'s own read line (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L80: `,p1.issue_dt` — (no edge served @80)
- L81: `,p1.loan_ori_maturity_dt` — (no edge served @81)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — canonical LFS133) (edge: SCHEMA/structure @82, `p6@155` → `lending_ref@82` — canonical LFS134) (dropped — USER RULING 2026-09-01: the sibling belongs-to SCHEMA/structure `loan_final@64` → `reserved_field8@82`, still served by the **full** view at this line — canonical LFS135 REMOVED)
- L183: `,p1.reserved_field8 AS reserved_field8` — (dropped — USER RULING 2026-09-01: the three sibling belongs-to rows SCHEMA/structure `p1@29` / `p1@84` / `p1@198` → `reserved_field8@82` — canonical LFS143/144/145 REMOVED) (dropped — field-involvement rule 3b: the write-projection read leg and the ⟐output membership, which the **full** view carries as `bdm_acc_loan_info_sup@160` → `reserved_field8@183` and `output@160` → `reserved_field8@82`)

*Example 2 — `charge_department` is a DYNAMIC partition (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L41: `INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)` — (edge: TABLE_FLOW/write leg @41, `output@41` → `east5_stzfxxb@41`) (edge: REF/read into output @41, `p_dt@41` → `output@41`) (edge: TABLE_FLOW/write value @41, `p_dt@41` → `output@41`) (dropped — USER RULING 2026-09-01: the sibling belongs-to SCHEMA/structure `east5_stzfxxb@41` → `CHARGE_DEPARTMENT@41` and `output@41` → `CHARGE_DEPARTMENT@41` ×2, still served by the **full** view here)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — USER RULING 2026-09-01: the source-CASE belongs-to SCHEMA/structure `a@141` → `charge_department@51`, still served by the **full** view) (dropped — field-involvement rule 3b: the sibling's feeding expression)

**3b — sibling value legs.**

*Example 1 — `reserved_field8`'s legs: born @82, written @183, read back at the p2 join (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the seed's own leg, kept) (dropped — field-involvement rule 3b: the sibling's own CASE value legs)
- L183: `,p1.reserved_field8 AS reserved_field8` — (dropped — field-involvement rule 3b: the write-projection read leg and ⟐output membership the **full** view carries here)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — (dropped — field-involvement rule 3b: the sibling's read-back leg; this line serves the seed's own `REF/read @199, lending_ref@201 → p2@199` and `TABLE_FLOW/chain (read into output) @199` instead)

*Example 2 — `charge_department`'s feeding expression and output routing (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L51: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)` — (dropped — field-involvement rule 3b: the sibling's COMPUTED/compute step `bdm_acc_entrusted_payment@141` → `east5_stzfxxb@41` with reason `‖a.charge_department@L51 → stzfdxzh@L53‖`, which the **full** view carries)

**3c — sibling chips.**

*Example 1 — the chip survives while a kept edge touches it (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ✅ chip in closure (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the ONE edge the sibling chip carries)

*Note:* `reserved_field8@82` stays because the seed's own CASE feeds it — edge-anchored by the searched field's flow, never by its belongs-to ("this column exists on this box" is a full-view fact).

*Example 2 — the edge-less co-filter chip is pruned with its belongs-to (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L263: `FROM bdm_acc_loan_info` — ✅ (edge: REF/read @263, `data_dt@19` → `bdm_acc_loan_info@19`) (edge: TABLE_FLOW/chain (read into output) @263, `bdm_acc_loan_info@19` → `output@253`)
- L264: `WHERE data_dt = '${load_date}'` — ✅ (edge: FILTER/filter step @264, `data_dt@19` → `bdm_acc_loan_info@19`)
- L265: `AND charge_department = 'OPS_CLBS_PLoan';` — (dropped — USER RULING 2026-09-01: no edge, and the edge-less `charge_department@265` chip pruned with it; canonical point 26)

### §4 TWINS

**4a — per-occurrence lines.**

*Example 1 — the CASE arms light at their own lines (EAST5, searching `charge_department`)*

- Search field: `east5_stzfxxb.charge_department` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; the audited lit set {54,55,56,66,68,70} is the doc's own record, and the **full** view shows the mechanism per line)
- L54: `CASE WHEN a.CHARGE_DEPARTMENT ="GTRF_CoreTrade_SCSAI" THEN a.entd_opp_acct_name` — (full view only: SCHEMA/structure @54, `bdm_acc_entrusted_payment@141` → `charge_department@51`; FILTER/row selection @54, `bdm_acc_entrusted_payment@141` → `output@41`)
- L55: `WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_acct_name,f.df_dfhm)` — (full view only: SCHEMA/structure @55, `bdm_acc_entrusted_payment@141` → `charge_department@51`; FILTER/row selection @55)
- L56: `WHEN a.charge_department = "OPS_MBS" THEN REGEXP_REPLACE(` — (full view only: SCHEMA/structure @56, same endpoints; FILTER/row selection @56)
- L66: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_no,f.df_dfxh)` — (full view only: SCHEMA/structure @66, same endpoints; FILTER/row selection @66)
- L68: `CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN NVL(a.entd_opp_bank_name,f.df_dfxm)` — (full view only: SCHEMA/structure @68, same endpoints; FILTER/row selection @68)
- L70: `CASE WHEN a.charge_department = 'GTRF_RFN' THEN a.remark` — (full view only: SCHEMA/structure @70, same endpoints; FILTER/row selection @70)

*Note:* each occurrence at its own line, never one merged blob. The SQL text also carries an occurrence at L51 that the audited lit set does not count.

*Example 2 — two occurrences → two twins, two lines (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a snapshot seed; no payload to check against)
- L37: `AND podtao <> pofddt` — (edge: not verified against payload — line cited from SQL only)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — (edge: not verified against payload — line cited from SQL only)

**4b — JOIN-ON AND-legs.**

*Example 1 — one JOIN, three AND-legs (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ nothing served here in this closure (`data_dt` is a sibling: field-involvement rule 3b; the **full** view carries the leg's JOIN/join step @202, `bdm_acc_loan_info_sup@160` → `output@160`)
- L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ nothing served here (same sibling drop; the **full** view carries JOIN/join step @203)

*Note:* the searched field's own leg anchors its own line; a sibling leg's line is dark in this closure.

*Example 2 — the AND-continuation leg (PL, searching `p_dt`)*

- Search field: `ODS_CUPD_PLOAN_ACCTM_NEW5.p_dt` (script: BDM_ACC_LOAN_INFO_PL.sql — not a snapshot seed; no payload to check against)
- L224: `AND a.p_dt = c.p_dt` — (edge: not verified against payload — line cited from SQL only)

*Note:* L224 is the JOIN's own continuation leg (the `ON` is at L223); L221's `c.p_dt` sits on its own JOIN line, not a continuation.

**4c — no duplicate anchor.**

*Example 1 — the NVL read is anchored ONCE (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L82: `,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8` — ✅ (edge: COMPUTED/compute step @82, `lending_ref@82` → `reserved_field8@82` — the seed's own edge; no twin re-anchors the line) (edge: SCHEMA/structure @82, `p6@155` → `lending_ref@82`)

*Example 2 — the LPAD twin anchors its line once (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a snapshot seed; no payload to check against)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — (edge: not verified against payload — line cited from SQL only)

**4d — no owner evidence → no twin.**

*Example 1 — the paren-scope owner rule (EAST5, searching `org_no_cbrc`)*

- Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed; the FULL-view rows below are what the flow-only view refuses to duplicate)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — (full view only: SCHEMA/structure @43, `c@145` → `org_no_cbrc@43` and `d@148` → `org_no_cbrc@43`; TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41`)

*Note:* the old text cites L42 — that line is a SQL comment in the sample; the NVL line is L43. `d.`'s bare occurrence earns no second twin.

*Example 2 — the outer group never claims a paren-scope line (SUP_M, searching `podtao`)*

- Search field: `ods_hub_lsacmsp.podtao` (script: BDM_ACC_LOAN_INFO_SUP_M.sql — not a snapshot seed; no payload to check against)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — (edge: not verified against payload — line cited from SQL only; `_paren_scope_bound` / `_scope_line_owner` keep the line with LPAD(...)'s own scope)

### §5 FOLD

**5a — multi-anchor (N lines → N edges).**

*Example 1 — three join sites in the CTE zone, one edge per line (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L95: `ON p1.lending_ref = accu.vlookup_key_value` — ✅ (edge: JOIN/join step @95, `lending_ref@13` → `loan_final@64`)
- L117: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ✅ (edge: JOIN/join step @117, `lending_ref@13` → `loan_final@64`)
- L150: `ON RPAD(p4.iiapty,3,'')||p4.iiblno = p1.lending_ref` — ✅ (edge: JOIN/join step @150, `lending_ref@13` → `loan_final@64`)
- L156: `ON p6.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @156 ×2 — `lending_ref@13` and `lending_ref@82`, one per occurrence; canonical LFS117 + LFS138)

*Note:* the served closure anchors FOUR join lines into `loan_final` (5 edges, because L156 carries one per side) plus a fifth anchor at L201 — `JOIN/join step @201, lending_ref@201 → output@160`. L41's CONCAT join key (the main table's other cite) serves nothing in this flow-only closure: that anchor is a **full**-view fact.

*Example 2 — the same mechanism per AND-leg (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`) (edge: SCHEMA/structure @201, `p2@199` → `lending_ref@201`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ sibling leg, dropped (field-involvement rule 3b; the **full** view carries the leg's JOIN/join step @202)
- L203: `AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'` — ❌ sibling leg, dropped (the **full** view carries JOIN/join step @203)

**5b — Fix H keeper-line.**

*Example 1 — the carrier standing ON the chip's own line wins (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L163: `,p1.lending_ref` — ✅ (edge: SCHEMA/structure @163, `p1@84` → `lending_ref@163`) (edge: SCHEMA/structure @163, `p1@198` → `lending_ref@163`)
- L198: `loan_final p1` — ✅ (edge: REF/read @198, `lending_ref@163` → `p1@198` — the alias-instance line, canonical LFS146's class)

*Note:* a carrier standing on a PROJECTION line does NOT win — L82/L163 are projection lines: the pinned Class-1 / LFS123 doctrine.

*Example 2 — the same fold on the write target's chip (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L254: `SELECT '${load_date}' AS data_dt,` — ✅ (edge: TABLE_FLOW/write value @254, `data_dt@254` → `output@253`) (edge: SCHEMA/structure @254, `output@253` → `data_dt@254`) — resolved by ruling 7-A (write leg only, 2026-09-01)
- L253: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt,object_domain,sub_src_system,table_name,job_name,total_rows,load_time,STATUS,remarks)` — ✅ (edge: TABLE_FLOW/write leg @253, `output@253` → `rrcdm_job_log_exec_par@253`)

**5c — line-0 guard.**

*Example 1 — the TVF alias carries a real line (RFN × `cust_no`)*

- Search field: `ods_gdc_split_fg_rating_temp.cust_no` (script: BDM_ACC_LOAN_INFO_RFN.sql)
- L1103: `WHEN SUBSTR(A.LOAN_IN_ACCT_NO,1,6) = 'CNHSBC' AND EXISTS (SELECT 1 FROM v_bdm_customer_all('${load_date}') a` — ✅ (edge: ALIAS/chain (alias hop) @1103, `v_bdm_customer_all@1103` → `a@1103`)

*Note:* M-T1's `skip_parens` gave the alias its real call line — the TVF box is `v_bdm_customer_all@1103`, not `@0`.

*Example 2 — no served edge ever anchors line 0 (all five flagship closures)*

- Search field: all five flagship snapshots' seeds (scripts: Digitallending / PL / RFN / SUP_M / EAST5 — measured)
- (measured on the regenerated baselines: 173 flow-only edges / 86 nodes across the five closures, **0** with a highlight line < 1; `_pick_anchor` excludes `line_start < 1`)

*Note:* line 0 still exists in the **full** view — RFN's unfiltered graph holds 11 line-0 SCHEMA/structure edges (e.g. `temp_dqrq_bulk@128` → `IFX13@0`) and 7 line-0 chips; none of them survives the fold into the flow-only view.

**5d — claimed-together.**

*Example 1 — the join-key line is already claimed (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L41: `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) = p1.lending_ref` — ❌ (edge: not verified against payload — line cited from SQL only; this flow-only closure serves nothing at L41, so the podtao group earns no SECOND edge here)

*Example 2 — the line claimed by another field's read (EAST5, searching `org_no_cbrc`)*

- Search field: `bdm_pub_branch.org_no_cbrc` through `NVL(c.org_no_cbrc,d.org_no_cbrc)` (script: EAST5_STZFXXB_M.sql — not a snapshot seed)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — ❌ (full view only: TRANSFORM/compute step @43, `bdm_pub_branch@145` → `east5_stzfxxb@41`; `d.`'s line is claimed by `c`'s read — no extra fold edge)

**5e — no cross-statement instance duplication.**

*Example 1 — the occurrence stays with its own statement (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199`) (edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160`)
- L201: `p2.lending_ref = p1.lending_ref` — ✅ (edge: JOIN/join step @201, `lending_ref@201` → `output@160`)
- L202: `AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')` — ❌ sibling leg, dropped here (field-involvement rule 3b); the R46d emission that folded this occurrence onto the job-log instance (`bdm_acc_loan_info_sup@223`) is the canonical's point-23(a) NOT-PINNED refusal

*Example 2 — the job-log statement's own instance (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — resolved by ruling 7-A: the log never writes this field — nothing shows (final state)

**5f — no foreign-owner guessed fold.**

*Example 1 — `T_BRANCH.data_dt` attributes to `T_BRANCH` (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250 — the occurrence's owner is `BDM_PUB_HSBC_ACCT_BRANCH` and `a` has no token on the line; the **full** view serves only the sibling chip's own SCHEMA/structure `T_BRANCH@250` → `data_dt@250`; canonical point 23(b): the two folded engine edges are NOT PINNED)

*Example 2 — attribution stays with the join owner (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199` — the fold stays with `p2@199`, never re-attributed to the searched compound without owner evidence)

### §6 GATE (value-cone)

**6a — cross-table same-name seeds excluded.**

*Example 1 — `T_BRANCH.data_dt` cannot lend its closure (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250; the foreign same-name chip is excluded — canonical point 23(b) NOT PINNED)
- L251: `WHERE a.p_dt = '${load_date}' and a.rn='1';` — ❌ (no edge served @251 — `a.p_dt` is another field of another table; the **full** view carries `a`'s own FILTER/row selection and value-copy rows here, all excluded from this closure)

*Example 2 — the searched `data_dt` vs EAST5's own `p_dt` family (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L43: `SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,` — ❌ (no edge served @43 in this closure — `c.data_dt`/`d.data_dt` of `bdm_pub_branch` are the same-NAME, different-TABLE class; the old text cites L42, which is a SQL comment line in the sample)
- L190: `WHERE p_dt = '$(load_date)'` — ✅ (edge: FILTER/filter step @190, `p_dt@41` → `east5_stzfxxb@41` — the searched table's own predicate, for contrast)

**6b — foreign statement trunks excluded.**

*Example 1 — the job-log trunk drops (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L211: `INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, sub_src_system, table_name, job_name, total_rows, load_time, STATUS, remarks)` — ❌ (no edge served @211)
- L213: `'$(load_date)' AS data_dt` — ❌ (no edge served @213 — the statement writes only literals + COUNT(1): ⚡ 7-A shapes this)
- L223: `bdm_acc_loan_info_sup` — ❌ (no edge served @223 — the statement READS the searched table's output but the whole trunk drops)

*Example 2 — the byte-identical trunk the engine DOES serve (EAST5 × `p_dt`)*

- Search field: `east5_stzfxxb.p_dt` (script: EAST5_STZFXXB_M.sql)
- L179: `INSERT INTO TABLE rrcdm_job_log_exec_par( data_dt ,object_domain ,sub_src_system ,table_name ,job_name ,total_rows ,load_time ,STATUS ,remarks )` — ✅ (edge: TABLE_FLOW/write leg @179, `output@179` → `rrcdm_job_log_exec_par@179`)
- L189: `FROM EAST5_STZFXXB` — ✅ (edge: TABLE_FLOW/chain (read into output) @189, `east5_stzfxxb@41` → `output@179`) (edge: REF/read @189, `p_dt@41` → `east5_stzfxxb@41`)
- L190: `WHERE p_dt = '$(load_date)'` — ✅ (edge: FILTER/filter step @190, `p_dt@41` → `east5_stzfxxb@41`)

*Note:* this pair IS the ⚡7-A inconsistency the doc describes — EAST5's trunk is served, SUP_M's (and DL's, @549) is dropped, PL's (@253/@254) is served.

**6c — foreign-owner folds respected.**

*Example 1 — the gate never re-parents (PL × `data_dt`)*

- Search field: `bdm_acc_loan_info.data_dt` (script: BDM_ACC_LOAN_INFO_PL.sql)
- L250: `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'` — ❌ (no edge served @250 — the edge's owner stays `T_BRANCH`; the searched compound is never handed it without owner evidence)

*Example 2 — the fold stays with its own owner (SUP_M × `lending_ref`)*

- Search field: `rollover_loan_info.lending_ref` (script: BDM_ACC_LOAN_INFO_SUP_M.sql)
- L199: `LEFT JOIN bdm_acc_loan_info_sup p2` — ✅ (edge: REF/read @199, `lending_ref@201` → `p2@199`; edge: TABLE_FLOW/chain (read into output) @199, `p2@199` → `output@160` — the fold stays with `p2@199`, never re-attributed to the searched compound without owner evidence)

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

### ⚡ 7-C. The sibling same-name REF edge (`src_b.dt` → `src_a.dt`'s closure)

The extractor builds a same-name REF edge between two tables' same-named columns; the walker can ride it into the sibling's closure. Under the field-involvement principle this is other-field flow → the traversal excludes it. (The *edge* is a real extraction fact — the question is whether the *walker* traverses it.)

### ⚡ 7-D. The ⟐output membership edges of sibling chips

When a sibling chip is admitted (co-written projection), its ⟐output membership SCHEMA edge rides along. J1's rule drops sibling VALUE edges but keeps sibling belongs-to/membership — the exact boundary needs the value-cone ruling (the full R-GATE, v3.3.195).

**RULED 2026-09-01 (later the same day): the "keeps sibling belongs-to/membership" half above is
SUPERSEDED** — point 26 rule 1 of the user ruling drops a SIBLING's belongs-to from the flow-only
closure (rule 3a row above); the value-cone R-GATE (v3.3.195) handles the value side. See §7-B.

**UPDATE 2026-09-01 (evening): 7-D now BLOCKS something concrete.** The
determinism fix (canonical dependency order, killing the PYTHONHASHSEED
instability the snapshot harness documents) was proven end-to-end and
reverted at the gate for exactly this reason: with the canonical order, the
walk admits ONE sibling chip + one routed REF edge the natural-order walk
did not (PL filtered, `data_dt` seed: `CHARGE_DEPARTMENT`@L19, precision
N 1.0000 → 0.875). Whether that sibling membership belongs in the closure
IS this ruling. The full landing recipe is preserved in the xfail reason of
`backend/tests/test_l2_determinism.py::test_l2_full_view_is_byte_identical
_across_hash_seeds`; landing after the 7-D ruling is a ~15-minute job.

---

# Summary — the decision tree

```
Is the edge about the SEARCHED field's VALUE?
├── YES → shown (read/write/compute/filter/join-key/group-key/window-key/
│         occurrence twin/AND-leg, each at its own line)
├── Is it STRUCTURAL SKELETON (headers, belongs-to, containers, aliases) → shown as context
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
