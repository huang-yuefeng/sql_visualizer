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
| 2g | A statement writes a column **named** like the field but the **value is a literal/constant** | ❌ ⚡ | The job-log: `INSERT INTO rrcdm_job_log_exec_par(data_dt, ...) SELECT '$(load_date)' AS data_dt, COUNT(1)...` — see ruling 7-A |

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
re-told:

**Example 1 — co-written CASE sibling (SUP_M × `lending_ref`)**

```sql
L80:  ,p1.issue_dt              -- loan issue date
L81:  ,p1.loan_ori_maturity_dt  -- loan original maturity date
L82:  ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
L83:  FROM bdm_acc_loan_info p1
```

Searching `lending_ref`, L82 is `lending_ref`'s own read (the NVL check).
The SAME line also writes a different field: `reserved_field8`.

- ❌ dropped: `reserved_field8`'s belongs-to edge @82 (3a, this ruling),
  its CASE value legs, its ⟐output membership, its write-projection read
  leg (3b). Under the old rule four belongs-to edges (LFS135, LFS143-145)
  kept the chip anchored — all gone.
- ✅ still present: the `reserved_field8` **chip itself** — the seed's
  own COMPUTED edge feeds it at L82 (the CASE that computes
  `reserved_field8` READS `lending_ref`), so the confirmed prune KEEPS
  it: it is edge-anchored by the searched field's own flow, not by its
  belongs-to.

Read the picture as: "`reserved_field8` appears because YOUR value flows
into it" — never "…and it also exists on this box" (that fact is a
full-view fact now).

**Example 2 — co-filter sibling (PL × `data_dt`)**

```sql
L263: FROM bdm_acc_loan_info            -- inside the searched table's own statement
L264: WHERE p1.data_dt = '${load_date}' -- the searched field's predicate
L265: AND   charge_department = 'OPS_CLBS_PLoan'  -- a SIBLING field's predicate
```

Searching `bdm_acc_loan_info.data_dt`: L265 filters rows by a different
field of the same table. Under the confirmed ruling the served filtered
closure carries NO trace of `charge_department` — no edge, and its chip
@265 (edge-less) is pruned with it. `data_dt`'s own predicate @264 is
untouched (2d). This is also the row J12-20 pinned and the **resolved**
§7-B — resolved then by ADDING the chip; the belongs-to that anchored it
is now dropped, and the edge-less chip removed, by this ruling.

**Example 3 — dynamic-partition co-write (EAST5 × `p_dt`)**

```sql
L41:  INSERT OVERWRITE TABLE east5_stzfxxb
      PARTITION(p_dt='$(load_date)', charge_department)   -- p_dt literal, charge_department DYNAMIC
L42:  SELECT ... , <expr> AS charge_department, ... FROM ...
```

Searching `east5_stzfxxb.p_dt`: L41 is `p_dt`'s own write (a literal
partition value — rule 2g). The same PARTITION clause co-writes
**`charge_department`** as a DYNAMIC partition. Under the confirmed
ruling: its belongs-to edges @41 (target box) and @51 (the producing
CASE) are DROPPED, its feeding SELECT expression is dropped (3b), and
its edge-less chips are pruned with them. This is the shape that
motivated the ruling: write-heavy statements co-write dozens of columns,
and under the old rule every one of them dragged a chip + belongs-to
edge into the closure.

**One-sentence summary for all three**: the searched field's closure
shows only what the searched field's own value drives — a sibling has no
edges and no edge-less chips in it. "What else is written on this line /
this box" is a question for the full view.

---

### Worked examples — the other rule groups

Three complete cases per group, same convention: real flagship SQL, what
is shown (✅) vs dropped (❌), and why.

**§1 SEEDS — where the closure starts**

1. *1a, own-table occurrence*: search `lending_ref` → every `p1.lending_ref`
   chip on the `bdm_acc_loan_info` compounds seeds. ✅ The L82 NVL read is
   the first lit line.
2. *1b, alias expansion (#399)*: `FROM v_bdm_customer_all('...') a`,
   search `a.cust_no` → the TVF's projection carries the field and no
   entity hosts it directly, so the alias's owning entities seed. ✅ The
   TVF box enters the closure.
3. *1c, cross-table same-name (RC-A)*: search `bdm_acc_loan_info.data_dt`
   → the `c/d/e.data_dt` chips on `bdm_pub_branch` /
   `BDM_ACC_INTERNAL_COUNTERPARTY` are same-NAME, different-TABLE — they
   do NOT seed. ❌ Their closures stay dark (this was the R-GATE's fix).

**§2 VALUE — edges that carry the field's value**

1. *2d, filter*: `WHERE p1.data_dt = '${load_date}'` → the predicate edge
   on the searched compound shows; the highlight lands on the WHERE line.
2. *2e, join key*: `ON p6.lending_ref = p1.lending_ref` @156 → the JOIN
   edge shows at the join's own line (and ONLY there — a join edge
   anchored at a projection line is the Class-1 defect, dropped).
3. *2g, name-but-no-value*: the job-log `INSERT INTO
   rrcdm_job_log_exec_par(data_dt,...) SELECT '$(load_date)', COUNT(1)`
   writes a column NAMED like the field but the value is a literal —
   ⚡ **ruling 7-A pending** (see §7-A).

**§4 TWINS — the same field at many lines**

1. *4a, per-occurrence lines*: `charge_department`'s CASE arms light
   exactly at {54, 55, 56, 66, 68, 70} — each occurrence at its own line,
   never one merged blob.
2. *4b, JOIN-ON AND-legs*: `AND b.lending_ref = a.lending_ref` @144,
   `AND b.org_no = c.org_no` @147 — continuation legs of one JOIN get
   their own occurrence twins, so the highlight reaches the AND lines.
3. *4d, no owner evidence*: `d.org_no` @150 — the line's owner is already
   served by `b.org_no`'s twin; no duplicate twin is minted. ❌ No extra
   edge, no double highlight.

**§5 FOLD — which carrier represents the group**

1. *5a, multi-anchor*: `lending_ref` joining `loan_final` at lines
   95/117/150/156 → FOUR JOIN edges, one per line (the RC-B fix: one
   merged edge used to hide three of the four).
2. *5b, keeper-line*: among carriers of one group, the one standing on
   the chip's own line wins the fold (Fix H) — the served edge's anchor
   is the line you'd click.
3. *5d, claimed-together*: the LFS108 NOT-IN filter — a group whose line
   another relationship already claims earns no second edge. ❌ One
   story per line.

---

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

```sql
-- SUP_M L162-163  search lending_ref → the projection occurrences seed
    p1.internal_key
    ,p1.lending_ref          -- ← seeds here (write-projection occurrence)
    ,p1.contract_no
```

```sql
-- EAST5 L41-42  search east5_stzfxxb.p_dt → the partition-key occurrence seeds
INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)
SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,
```

**1b — alias/TVF expansion (#399).**

```sql
-- the TVF form: search a.cust_no through FROM v_bdm_customer_all('...') a
--   → the TVF's projection carries the field, so the alias's owning entities seed
```

```sql
-- RFN — the plain alias-qualified form (the FSC-2 case): search a.cust_no
--   → before the model persistence fix this seed was LOST (search_matched: false,
--   the whole 1053-node graph served); after it the 78-node closure serves
```

**1c — cross-table same-name does NOT seed.**

```sql
-- SUP_M L199-202  search bdm_acc_loan_info.data_dt: p2 IS the searched table's
--   sup instance → its data_dt occurrence SEEDS the join leg (that's 2e, not 1c)
    LEFT JOIN bdm_acc_loan_info_sup p2
    ON
        p2.lending_ref = p1.lending_ref
        AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')
```

```sql
-- PL L221  search the searched table's data_dt: c.p_dt is a same-NAME,
--   different-TABLE column (ODS_CUPD_PLOAN_APS_CREDINF5) → does NOT seed
LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'
```

### §2 VALUE

**2a — reads.**

```sql
-- SUP_M L163  SELECT projection read
    ,p1.lending_ref          -- the searched field's value is read here
```

```sql
-- DL L100-101  SELECT-projection read that births the alias (canonical row X5)
INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)',...)
SELECT
A.acctnbr AS LENDING_REF   -- the read that produces the output column
```

**2b — writes.**

```sql
-- SUP_M L155  the value lands in the write target
        LEFT JOIN rollover_loan_info p6
        ON p6.lending_ref = p1.lending_ref
```
(served with the statement's `INSERT OVERWRITE TABLE bdm_acc_loan_info_sup`
write edge — the write leg is the searched field's own)

```sql
-- EAST5 L41  p_dt's own write line (a literal partition value — see 2g)
INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)
```

**2c — computes.**

```sql
-- SUP_M L41  the searched field inside a join-key expression
ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
```

```sql
-- RFN L1117-1119  dm_flag2 is COMPUTED by a CASE mask (its audited written-768 step)
OR (regexp_instr(A.LOAN_IN_ACCT_NAME,'[A-Za-z]+$') >= 1 AND ...)
THEN 'NI'
END AS DM_FLAG2
```

**2d — filters.**

```sql
-- PL L264  the searched field's own predicate
WHERE data_dt = '${load_date}'
```

```sql
-- SUP_M L37  searching podtao: its own predicate arm at its own line
                            AND podtao <> pofddt
```

**2e — join keys.**

```sql
-- SUP_M L156  the searched field IS the join operand
        LEFT JOIN rollover_loan_info p6
        ON p6.lending_ref = p1.lending_ref
```

```sql
-- PL L221  searching acnw: its operand edge shows at the join line
LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'
```

**2f — group/window keys.**

```sql
-- PL L243-247  product decides grouping (the Reappears step)
group by arrangement_local_number,
cb_pointer,
account,
product,
lrr_key) km1
```

```sql
-- DL L64  acnw decides ranking — window PARTITION BY
,ROW_NUMBER() OVER(PARTITION BY p1.acnw ORDER BY SSALSFP.P_DT DESC) RN
```

**2g — named-but-literal write (⚡ ruling 7-A).**

```sql
-- SUP_M L210-213  the job-log: data_dt is WRITTEN but its value is a LITERAL
-- operation-log record
INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, object_domain, ...)
SELECT
    '$(load_date)' AS data_dt
```

```sql
-- EAST5 L41  the partition slot named like the field, fed by a literal
INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)
```

### §3 SIBLINGS (post-ruling)

**3a — sibling belongs-to (dropped by the 2026-09-01 ruling).**

```sql
-- SUP_M L80-82  reserved_field8 is BORN on lending_ref's own read line
        ,p1.issue_dt
        ,p1.loan_ori_maturity_dt
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
-- pre-ruling: reserved_field8's belongs-to anchors @82/@183 stayed; post-ruling: dropped
```

```sql
-- EAST5 L41+L51  charge_department is a DYNAMIC partition (its CASE feeds it)
INSERT OVERWRITE TABLE east5_stzfxxb PARTITION(p_dt='$(load_date)',charge_department)
...
CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,...)
-- its belongs-to @41 (target) and @51 (source CASE): dropped the same way
```

**3b — sibling value legs.**

```sql
-- SUP_M  reserved_field8's legs: born @82, written by the L183 projection,
--   read back at the p2 join — ALL its value legs drop
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
```

```sql
-- EAST5 L51  charge_department's feeding expression and output routing drop
CASE WHEN a.charge_department IN("WPB_RBB","OPS_CDT") THEN COALESCE(e.acct_no,a.entd_opp_acct_no,f.df_dfzh)
```

**3c — sibling chips.**

```sql
-- SUP_M L82  reserved_field8's chip survives ONLY because lending_ref's own
--   CASE (the NVL read) feeds it — edge-anchored by the searched field's flow
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
```

```sql
-- PL L265  charge_department co-filters data_dt's rows — post-ruling: NO trace
FROM bdm_acc_loan_info
WHERE data_dt = '${load_date}'
AND charge_department = 'OPS_CLBS_PLoan';
```

### §4 TWINS

**4a — per-occurrence lines.**

```sql
-- EAST5 L51-70 (charge_department CASE arms: L51/55/56/66/68/70) — each arm lights at its own audited line: {54,55,56,66,68,70}
```

```sql
-- SUP_M L37 + L41  podtao's two occurrences → two twins, two lines
                            AND podtao <> pofddt
...
ON CONCAT(...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
```

**4b — JOIN-ON AND-legs.**

```sql
-- SUP_M L201-203  one JOIN, three AND-legs: lending_ref @201, data_dt @202,
--   charge_department @203 — each leg anchors its own line
        p2.lending_ref = p1.lending_ref
        AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')
        AND p2.charge_department = 'GTRF_CoreTrade_EPBL_MYRZ'
```

```sql
-- PL L221  the AND-continuation leg c.p_dt anchors its own line
LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON c.sxxyh = a.acnw AND c.p_dt = '${load_date}'
```

**4c — no duplicate anchor.**

```sql
-- SUP_M L82  the NVL read is anchored ONCE (the seed's own edge) — no twin re-anchors it
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
```

```sql
-- SUP_M L41  podtao's LPAD twin anchors L41 once — never re-anchoring L37's carrier
ON CONCAT(...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
```

**4d — no owner evidence → no twin.**

```sql
-- EAST5 L42  c/d org_no_cbrc live INSIDE NVL — a bare occurrence with no clause
--   owner of its own earns no twin (the paren-scope owner rule)
SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,
```

```sql
-- SUP_M L41  podtao's L41 line belongs to LPAD(...)'s own paren scope
--   (_paren_scope_bound / _scope_line_owner) — the outer group never claims it
ON CONCAT(...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
```

### §5 FOLD

**5a — multi-anchor (N lines → N edges).**

```sql
-- SUP_M: lending_ref anchors THREE join sites at THREE lines → three edges
L41:  ON CONCAT(...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
L156: ON p6.lending_ref = p1.lending_ref
L201:     p2.lending_ref = p1.lending_ref
```

```sql
-- SUP_M L201-203  the same mechanism per AND-leg: 3 legs → 3 line anchors
```

**5b — Fix H keeper-line.**

```sql
-- SUP_M  the carrier standing ON the keeper chip's own line wins the fold
--   (R45 Fix H); a carrier standing on a PROJECTION line does NOT —
--   L82/L163 are projection lines: the pinned Class-1 / LFS123 doctrine
        ,CASE WHEN NVL(p6.lending_ref,'') <> '' THEN 'Rollover2' END AS reserved_field8
```

**5c — line-0 guard.**

```sql
-- the TVF form: v_bdm_customer_all('...') a — the alias anchored L0 until
--   M-T1's skip_parens gave it its real call line
```

```sql
-- synthetic nodes: every ⟐output / union-branch carries line 0 BY CONSTRUCTION
--   and can never anchor anything (_pick_anchor excludes line_start < 1)
```

**5d — claimed-together.**

```sql
-- SUP_M L41  the join-key line is already claimed by the JOIN edge —
--   the podtao group's fold earns no SECOND edge on the same line
ON CONCAT(...,LPAD(p2.podtao,8,'0')) = p1.lending_ref
```

```sql
-- EAST5 L42  d.org_no_cbrc's line is claimed by c's NVL read — no extra fold edge
SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,
```

**5e — no cross-statement instance duplication.**

```sql
-- SUP_M L199-202  p2.data_dt @202 is owned by THIS statement's join (p2@199);
--   it is never duplicated onto the L211 job-log statement's instance
    LEFT JOIN bdm_acc_loan_info_sup p2
    ON
        p2.lending_ref = p1.lending_ref
        AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')
```

**5f — no foreign-owner guessed fold.**

```sql
-- PL L250  T_BRANCH.data_dt attributes to T_BRANCH — never re-parented onto
--   the searched compound without owner evidence (FSB phantom class, J2 defect B)
LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON a.ctcd||a.gmab||LPAD(a.acb,3,'0') = T_BRANCH.branch_code AND T_BRANCH.data_dt = '${load_date}'
```

```sql
-- SUP_M L201-202  attribution stays with the join owner p2@199 — the value-cone
--   never re-parents the occurrence onto bdm_acc_loan_info_sup
```

### §6 GATE (value-cone)

**6a — cross-table same-name seeds excluded.**

```sql
-- PL L250-251  T_BRANCH.data_dt (different table, same name) cannot lend its
--   closure to the searched bdm_acc_loan_info.data_dt
LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON ... AND T_BRANCH.data_dt = '${load_date}'
WHERE a.p_dt = '${load_date}' and a.rn='1';
```

```sql
-- EAST5 L42  the searched data_dt vs EAST5's own p_dt family — a different
--   table's same-named field never seeds (the RC-A/R-GATE class)
SELECT NVL(c.org_no_cbrc,d.org_no_cbrc) As jrxkzh,
```

**6b — foreign statement trunks excluded.**

```sql
-- SUP_M L210-213  the job-log statement READS the searched table's output
--   (FROM bdm_acc_loan_info_sup, L222) but writes only literals + COUNT(1):
--   the whole trunk drops from lending_ref's closure (⚡ 7-A shapes this)
INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, ...)
SELECT '$(load_date)' AS data_dt, ... FROM bdm_acc_loan_info_sup
```

**6c — foreign-owner folds respected.**

```sql
-- PL L250  the gate never re-parents: the edge's owner stays T_BRANCH
LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON ... AND T_BRANCH.data_dt = '${load_date}'
```

```sql
-- SUP_M L201-202  the fold stays with p2@199 — never re-attributed to the
--   searched compound without owner evidence
```

---

## ⚡ 7. THE RULING ITEMS — where the rules conflict

### ⚡ 7-A. The job-log continuation (R29 vs the field-involvement rule) — BLOCKING

```sql
L155:  INSERT OVERWRITE TABLE bdm_acc_loan_info_sup ...   ← the value lands here ✅
L211:  INSERT INTO TABLE rrcdm_job_log_exec_par(data_dt, ...)
L212:  SELECT '$(load_date)' AS data_dt, COUNT(1) ...     ← NO field value — a log/count
L222:  FROM bdm_acc_loan_info_sup
```

- **R29 (2026-08-12) says: SHOWN** — "the graph must be one connected flow": without the bridge it breaks into two islands.
- **The field-involvement rule says: NOT shown** — the log-write carries a count + literals, no field value. FSA measured: **76 fields' stories claimed "consumed @179"** by this same log-write.
- **Currently the engine is inconsistent**: EAST5's log-write trunk is shown; SUP_M/iiapty's is dropped.
- **Decides**: 2 jaccard cases, 2 L1 doc tests, the ground-truth docs, and ~191 continuation legs across the flagships.

### ⚡ 7-B. The own-table co-filter sibling (J12-20 pin)

PL @265: `AND charge_department = 'OPS_CLBS_PLoan'` — an edgeless co-filter sibling on the searched table's own compound. J12-20 pinned it as a documented closure member; the DL mirror serves it; but the PL **filtered** view drops it (a filtered-path under-emission). **(J2 fixing.)**

### ⚡ 7-C. The sibling same-name REF edge (`src_b.dt` → `src_a.dt`'s closure)

The extractor builds a same-name REF edge between two tables' same-named columns; the walker can ride it into the sibling's closure. Under the field-involvement principle this is other-field flow → the traversal excludes it. (The *edge* is a real extraction fact — the question is whether the *walker* traverses it.)

### ⚡ 7-D. The ⟐output membership edges of sibling chips

When a sibling chip is admitted (co-written projection), its ⟐output membership SCHEMA edge rides along. J1's rule drops sibling VALUE edges but keeps sibling belongs-to/membership — the exact boundary needs the value-cone ruling (the full R-GATE, v3.3.195).

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
│   (the job-log) → ⚡ RULING 7-A PENDING
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
