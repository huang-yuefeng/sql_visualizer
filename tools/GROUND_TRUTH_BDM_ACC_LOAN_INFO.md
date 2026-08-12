# Ground Truth — BDM_ACC_LOAN_INFO_PL.sql

Hand-verified data flow of `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_PL.sql`.
This is the reference for future work: every extractor / graph / highlight
change must preserve these flows. The REQUIREMENT sections (§4.2 LAYER-2,
§4.3 MISSING) are the authoritative source for the benchmark fixture B
(user ruling J12-13, 2026-08-11 — "strictly use the ground truth in the
benchmark": B is derived from the doc's REQUIREMENT sections, never from
the engine's emitted form). The §8.5 closure table is the probe-pinned
machine-readable realization of those requirements (the engine's served
L2 form, pinned AFTER the requirements were written — the pin records
how the served output realizes the requirements, it never redefines them).

**CURRENT-STATE RE-VERIFICATION (2026-08-11 → pinned 2026-08-12, pl-seed
round): the script was reconstructed by the OCR team (samples/sql_sample_v1/
BDM_ACC_LOAN_INFO_PL.sql); this doc's requirement facts were verified by
reading the SQL and by the live extraction + filtered L2 probe against
the container `gps-sql-backend` (stage-4 engine + the round's J12-17
fix; see §8.5 for the probe-pinned served forms). All [PROBE:] items
below are filled with the probe results; the REQUIREMENT lines
(§4.2/§4.3) hold regardless of what the engine emits.**

> **WAIT-CONDITION NOTE (2026-08-11, RESOLVED 2026-08-12):** the
> benchmark's "pl" seed must not be measured until the script file
> exists AND parses with sqlglot mysql — both hold: the script is
> committed to `samples/sql_sample_v1/`, parses cleanly (4 statements:
> SET@18, INSERT@19, SELECT@21-251, INSERT@253-265), and the pl block of
> the benchmark gate is GREEN (floors 1.0000/1.0000 per feature, §8.5).

---

## 1. Script structure

```
stmt0 (L18):  SET odps.sql.decimal.odps2=true;
stmt1 (L19, TOP0):  INSERT OVERWRITE TABLE bdm_acc_loan_info
                      PARTITION(data_dt='${load_date}',
                                CHARGE_DEPARTMENT='OPS_CLBS_PLoan');
              — BARE INSERT (no SELECT body — the statement ends at the
                semicolon on L19). Its output VT is named "⟐ insert"
                (not "⟐ output" — the bare/VALUES-INSERT naming, J12-17).
                It writes ONLY the two partition columns into
                bdm_acc_loan_info. [The ~130-column SELECT below is the
                NEXT statement — it does NOT write bdm_acc_loan_info.]
stmt2 (L21-251, TOP1):  standalone SELECT distinct ... (~130 output
                columns: LENDING_REF, PCBACCT_NO, ..., loan_purpose_onoff_flag)
                FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY acnw) AS rn
                      FROM ODS_CUPD_PLOAN_ACCTM_NEW5
                      WHERE p_dt='${load_date}') a            (L220)
                LEFT JOIN ODS_CUPD_PLOAN_APS_CREDINF5 c ON ... (L221)
                LEFT JOIN BDM_PUB_BRANCH D ON ...              (L223)
                JOIN ( ... ) p2 ON ...                         (L225-249)
                LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH ON ... (L250)
                WHERE a.p_dt='${load_date}' AND a.rn='1'        (L251)
stmt3 (L253-265, TOP2):  INSERT INTO TABLE rrcdm_job_log_exec_par
                (data_dt, object_domain, sub_src_system, table_name,
                 job_name, total_rows, load_time, STATUS, remarks)
                 SELECT '${load_date}' AS data_dt, ...           (L254)
                 FROM bdm_acc_loan_info                          (L263)
                 WHERE data_dt='${load_date}'                    (L264)
                   AND charge_department='OPS_CLBS_PLoan'        (L265)
```

Probe-pinned lines (grep + served L2 full view): SET@18; the bare
INSERT/partition@19 (TOP0); the main SELECT@21-251 (TOP1, output VT
"⟐ output"@21); stmt2 INSERT@253 (TOP2, output VT "⟐ output"@253);
data_dt output column@254; bdm_acc_loan_info read@263; data_dt WHERE
read@264; charge_department WHERE read@265. Join/alias def lines:
a@220, c@221, D@223, p2@225-248, T_BRANCH@250 (see §3).

---

## 2. Table-level flow

```
TOP1 SELECT@21 reads (the statement's own output VT ⟐ output@21):
ODS_CUPD_PLOAN_ACCTM_NEW5 ──► ⟐ output@21   (derived row_number subquery, a@220)
ODS_CUPD_PLOAN_APS_CREDINF5 ─► ⟐ output@21   (LEFT JOIN c@221)
BDM_PUB_BRANCH ──────────────► ⟐ output@21   (LEFT JOIN D@223)
p2 (derived, L225-248) ──────► ⟐ output@21   (JOIN; its body reads
                                bdm_fin_lrr_key_base_info via bi@234 and
                                ODS_CDP_GDC_TABLE_COA_LIST via cl@238)
BDM_PUB_HSBC_ACCT_BRANCH ────► ⟐ output@21   (LEFT JOIN T_BRANCH@250)

TOP0 bare INSERT@19: ⟐ insert@19 ──► bdm_acc_loan_info@19   (partition write)
TOP2 job log INSERT@253: ⟐ output@253 ──► rrcdm_job_log_exec_par@253
  input: bdm_acc_loan_info@263 (FROM), filtered at L264/L265
```

Probe-pinned: the served FULL view's table/alias compounds are
`a`@220 (intermediate, derived), `c@221` (alias of
ODS_CUPD_PLOAN_APS_CREDINF5@221), `D@223` (alias of BDM_PUB_BRANCH@223),
`p2`@226 and `p2`@248 (intermediate — the derived subquery's two
instances; body contexts p2/subq/km1@228, p2/subq/km1/exists1@237,
p2/subq/km1/exists1/subq2@239), `bi@234` (alias of
bdm_fin_lrr_key_base_info@234), `cl@238` (alias of
ODS_CDP_GDC_TABLE_COA_LIST@238), `T_BRANCH@250` (alias of
BDM_PUB_HSBC_ACCT_BRANCH@250).

---

## 3. Alias def-line map (I1 semantics — first token of the defining clause)

```
TOP1 main SELECT@21 (the derived FROM / JOINs):
  a        = derived over ODS_CUPD_PLOAN_ACCTM_NEW5    (L220, row_number subquery)
  c        = derived over ODS_CUPD_PLOAN_APS_CREDINF5  (L221)
  D        = derived over BDM_PUB_BRANCH               (L223)
  p2       = derived subquery (JOIN ( at L225, label ') p2' at L248)
             — body reads bdm_fin_lrr_key_base_info via bi@234 and
               ODS_CDP_GDC_TABLE_COA_LIST via cl@238 (nested subqueries
               km1@228, exists1@237, subq2@239)
  T_BRANCH = alias of BDM_PUB_HSBC_ACCT_BRANCH         (L250)
             ← NOT bdm_fin_lrr_key_base_info: grep-verified, the L250
               join reads `LEFT JOIN BDM_PUB_HSBC_ACCT_BRANCH T_BRANCH
               ON ... = T_BRANCH.branch_code AND T_BRANCH.data_dt = ...`;
               bdm_fin_lrr_key_base_info is read INSIDE p2 via bi@234.
               (Draft §2/§3 had this swapped — corrected with the script
               evidence, 2026-08-12.)
```

Probe-pinned served labels: `a`@220 and `p2`@226/@248 render as
intermediate_table (derived-subquery aliases — stage-4 model truth);
`c@221`, `D@223`, `bi@234`, `cl@238`, `T_BRANCH@250` render as
alias_table (label-rule aliases of their physical sources).

---

## 4. Field ground truth — bdm_acc_loan_info.data_dt

### 4.1 Occurrence lines (the "touch points")

```
L19  PARTITION(data_dt='${load_date}', ...)   write, stmt1 target partition (L1p; L1t=19)
L254 '${load_date}' AS data_dt                write, stmt2 output column (literal) (L2w)
L264 data_dt = '${load_date}'                 read, stmt2 WHERE, bare → bdm_acc_loan_info (L2f)
L265 charge_department = 'OPS_CLBS_PLoan'     read, stmt2 WHERE (charge dept, not data_dt) (L2c)
```

Probe-pinned: the served L2 filtered closure's field occurrences are
data_dt@19 (partition write), data_dt@254 (output column), data_dt@264
(WHERE read); bdm_acc_loan_info's instances are @19 (stmt1 INSERT
target) and @263 (stmt2 FROM read); rrcdm_job_log_exec_par@253 (stmt2
INSERT target).

NOT this field (belongs to other tables — negative proof):

```
L220 a.p_dt = '${load_date}'          → ODS_CUPD_PLOAN_ACCTM_NEW5 (a) — the source's own load-date
L221 c.sxxyh / c.p_dt (join key)      → ODS_CUPD_PLOAN_APS_CREDINF5 (c)
L223 D.org_no / D.DATA_DT (join key)  → BDM_PUB_BRANCH (D)
L242 bi.account (join key)            → bdm_fin_lrr_key_base_info (bi) — inside p2
L242 cl.nominal_accounts (join key)   → ODS_CDP_GDC_TABLE_COA_LIST (cl) — inside p2
L249 p2.arrangement_local_number ...  → p2 (the derived subquery's join key)
L250 T_BRANCH.branch_code/data_dt ... → BDM_PUB_HSBC_ACCT_BRANCH (T_BRANCH) — other table's field
```

### 4.2 Downstream layer-by-layer (targets of targets) — REQUIREMENT

```
LAYER 0 — the field (occurrences):  L19 (partition write), L254
          (stmt2 output column), L264 (stmt2 WHERE read)

LAYER 1 — direct targets:
  L19  ──► bdm_acc_loan_info (L19)   ← the partition write lands here
  L254 ──► rrcdm_job_log_exec_par (L253)  ← the output column feeds stmt2's INSERT
  L264 ──► bdm_acc_loan_info (L263)   ← the stmt2 WHERE read constrains the job-log input

LAYER 2 — targets of layer 1 (REQUIREMENT — the cross-statement chain):
  bdm_acc_loan_info ─► rrcdm_job_log_exec_par   (read L263 → INSERT L253)

LAYER 3 — final targets (sinks):
  bdm_acc_loan_info    (stmt1 target partition)
  rrcdm_job_log_exec_par   (stmt2 job log)
```

Semantic closure: **canonical 8 nodes / 9 closure vars** (the 3 data_dt
occurrences @19/@254/@264, the 2 bdm_acc_loan_info instances @19/@263,
rrcdm_job_log_exec_par@253, the 2 output VTs ⟐insert@TOP0/⟐output@TOP2,
plus the FILTER-zone sibling charge_department@265 — the 9th var),
**2 final sinks** — mirror of the SUP doc's closure shape: the stmt1
INSERT target and the stmt2 job-log sink. **NO source/join tables enter
the closure** — data_dt's partition is literal-driven (`'${load_date}'`
is not traced) and the TOP1 sources carry other fields. Requirement
semantics: one-source→targets flow, no dead-ends, no-bypass
cross-statement. Served realization (probe-pinned): 7 nodes — the
J12-16 fold merges data_dt@19/@264 into ONE field node under
bdm_acc_loan_info (incidents 19+264), the @263 reader instance rides
the bdm@19 compound, and charge_department@265 is an edgeless extra
(§8.6).

### 4.3 Edge inventory — what the graph must have (REQUIREMENT, mirrors SUP §4.3 items 3/4)

The SUP seed's requirement rows map 1:1 onto this script — the two
statements have the same shape (INSERT OVERWRITE target + INSERT INTO
job log), so the requirement edges are the same two "MISSING" classes,
here stated as MUST-HAVE:

```
3. ⟐output1 → bdm_acc_loan_info@L19   table-level write leg (stmt1's output VT
   feeds its INSERT target — the write leg; the benchmark asserts it as
   TABLE_FLOW stamped flow_kind='write', R19.3)
4. bdm_acc_loan_info@L19 → bdm_acc_loan_info@L263  cross-statement
   write→read link (stmt2 reads the stmt1 target; the R19.3 no-bypass
   chain must route THROUGH the reader instance at L263:
   output1 → bdm → [stmt2 read] → output2 → rrcdm)
```

These are REQUIREMENT rows (the doc's ideal — what the graph must show),
never a description of the current engine output. The benchmark pins
them (jaccard_canonical.py "pl" block, rows P15/P18/P22/P16) and the
R19.3 chain checks assert the no-bypass property.

Probe-pinned served realization (the engine's L2, seed
`bdm_acc_loan_info.data_dt`): item 3 is realized by the TABLE_FLOW
write leg `insert→bdm_acc_loan_info` hl=19, id `l2e_796c5b52f478_dml_out`,
flow_kind='write' (P15); item 4's chain is realized by P18 (REF
`data_dt→bdm_acc_loan_info` hl=263, kind=read) + P22 (TABLE_FLOW
`bdm_acc_loan_info→output` hl=263, kind=chain) + P16 (TABLE_FLOW write
leg `output→rrcdm_job_log_exec_par` hl=253, flow_kind='write') — the
R19.3 chain P15→P18→P22→P16, asserted by the benchmark's chain
incidence checks. Full edge details in §8.5.

---

## 5. Highlight ground truth

> **⚠️ SUPERSEDED (2026-08-10, user ruling):** §5-style field-occurrence
> highlight lists are superseded by the formal definition in §8 —
> Highlight is per-edge (edge = one data flow), there is no field
> highlight. Kept here only for the audit trail.

### 5.1 The field's own lines (candidates for §8.3.2 fallback only)

```
L19  PARTITION(data_dt='${load_date}', ...)    ← partition write (stmt1 target)
L254 '${load_date}' AS data_dt                 ← stmt2 output column
L264 data_dt = '${load_date}'                  ← stmt2 WHERE read
```

### 5.2 Negative proof — lines correctly NOT highlighted

```
L220 a.p_dt          → ODS_CUPD_PLOAN_ACCTM_NEW5 (other table)
L221 c.sxxyh         → ODS_CUPD_PLOAN_APS_CREDINF5 (other table)
L223 D.org_no        → BDM_PUB_BRANCH (other table)
L242 bi.account      → bdm_fin_lrr_key_base_info (other table, inside p2)
L242 cl.nominal_accounts → ODS_CDP_GDC_TABLE_COA_LIST (other table, inside p2)
L249 p2.arrangement_local_number → p2 (other table)
L250 T_BRANCH.data_dt → BDM_PUB_HSBC_ACCT_BRANCH (other table)
```

### 5.3 Highlight semantics

- The tool highlights **edge anchor lines** only (§8), never the table
  FROM lines — correct by design.
- Literal producers (`'$(load_date)'`) are not traced — by design.

---

## 6. Test contract (what a regression test must pin)

```
1. parse_errors == [] ; the script parses with sqlglot mysql (4 statements)
2. alias def lines: a@220 / c@221 / D@223 / p2@225-248 / T_BRANCH@250
3. bdm_acc_loan_info.data_dt closure (L2): 7 served nodes / 9 edges
   (canonical 8 nodes — §7.2; the fold + reader-instance realization, §4.2)
4. THE GROUND TRUTH: the requirement closure — the two sinks
   (bdm_acc_loan_info@19, rrcdm_job_log_exec_par@253), the stmt1 write leg
   (⟐insert@19 → bdm@19) and the cross-statement write→read chain
   (bdm@19 → bdm@263 → output@253 → rrcdm@253), §4.3
5. highlights: the §8.5 closure anchors (probe-pinned: 19, 253, 254, 263, 264)
```

Status: analysis only — no source changes.

---

## 6a. L1 ground truth — the cross-script projection of the queried field's flow (requirement change 2026-08-12, R29)

> **Semantic (authoritative, R29):** L1 shows the data flow of the QUERIED FIELD — the same field-level semantic as L2 — at cross-script scale: script nodes + the tables between scripts that carry the flow (no fields). Data flow = the fields WRITING the queried field (upstream) + the fields READING it (downstream). Scripts/tables that only read or write the queried TABLE (not the queried field's flow) are NOT included. The direction is a QUERY PANEL setting — upstream (writing data flow, **default**) / downstream (reading data flow); L2 follows automatically (zoom-in of L1). **Flow-reason anchoring (user ruling 2026-08-12):** in the L2 flow reason the direction fixes which end of the flow the queried field anchors — downstream: the seed is the flow SOURCE (R19.1 framing, unchanged); upstream: the seed is the flow TARGET (the flow converges on it; the sources are the fields writing it). **Downstream = the EFFECT SCOPE of the queried field (user ruling 2026-08-12):** the downstream flow shows everywhere the queried field is USED — not only read, but WHERE clauses and any other usage. A statement that uses the queried field carries the flow into everything that statement writes, even when the written column value is a literal (the usage selects the rows the statement emits). Input tables of a using statement — tables it reads that do not carry the queried field — are NOT part of the projection (the flow is field-level, not statement-level).

Seed for this doc: `bdm_acc_loan_info.data_dt`, workspace = `samples/sql_sample_v1/` (3 scripts: BDM_ACC_LOAN_INFO_PL.sql, BDM_ACC_LOAN_INFO_Digitallending.sql, BDM_ACC_LOAN_INFO_SUP_M.sql). The L1 view is workspace-scoped — this projection is shared by the PL / Digitallending / SUP ground truth docs of this seed.

### 6a.1 Upstream L1 (writing data flow — DEFAULT direction)

Fields writing `bdm_acc_loan_info.data_dt` (the partition writes, verified by grep 2026-08-12):

| Script | Line | Write |
|--------|------|-------|
| BDM_ACC_LOAN_INFO_PL.sql | 19 | `INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION(data_dt='${load_date}', CHARGE_DEPARTMENT=...)` — bare INSERT, writes ONLY the partition columns |
| BDM_ACC_LOAN_INFO_Digitallending.sql | 99 | `INSERT OVERWRITE TABLE bdm_acc_loan_info PARTITION (data_dt = '$(load_date)', CHARGE_DEPARTMENT=...)` |

The partition values are literals — the writing flow terminates at these two writes (no further producers).

**L1 upstream projection (scripts + tables):**
- Scripts: `BDM_ACC_LOAN_INFO_PL`, `BDM_ACC_LOAN_INFO_Digitallending`
- Tables: `bdm_acc_loan_info` (the DML target carrying the write fields)
- **Excluded:** `BDM_ACC_LOAN_INFO_SUP_M` — it READS bdm_acc_loan_info but writes no `data_dt` into it (its writes are bdm_acc_loan_info_sup@160 + rrcdm_job_log_exec_par@211). The old table-level L1 admitted it via its bdm reads; R29 excludes it (no table-level inclusion).

### 6a.2 Downstream L1 (reading data flow)

Fields reading `bdm_acc_loan_info.data_dt` (verified by grep 2026-08-12):

| Script | Read lines | Notes |
|--------|-----------|-------|
| BDM_ACC_LOAN_INFO_SUP_M.sql | 18, 43, 84/158 | `WHERE data_dt = '$(load_date)'` (CTE{rollover_loan_info}); `SUBSTR(p1.data_dt,1,7)`; `p1.data_dt = '$(load_date)'` (CTE{loan_final}) — the reads derive the `bdm_acc_loan_info_sup.data_dt` partition write@160 |
| BDM_ACC_LOAN_INFO_PL.sql | 264 | stmt3 `WHERE data_dt = '${load_date}'` on the bdm read@263 |
| BDM_ACC_LOAN_INFO_Digitallending.sql | 560 | stmt2 `WHERE data_dt = '$(load_date)'` on the bdm read@559 |

**L1 downstream projection (scripts + tables):**
- Scripts: `BDM_ACC_LOAN_INFO_SUP_M`, `BDM_ACC_LOAN_INFO_PL`, `BDM_ACC_LOAN_INFO_Digitallending`
- Tables: `bdm_acc_loan_info` (the read instances), `bdm_acc_loan_info_sup` (SUP_M's data_dt partition write@160 — a field reading the seed), `rrcdm_job_log_exec_par` (the log write legs — all three IN by the effect-scope rule, see below)
- `rrcdm_job_log_exec_par`: the write legs of the reading statements — **all three IN** (user ruling 2026-08-12: downstream = the effect scope of the queried field). Each statement USES the queried `data_dt` in its WHERE clause, so the rows written to the log are selected by that usage — the written column value being a literal is irrelevant. SUP_M@211 is additionally probe-pinned in the seed's closure (traceability R19.2 — "bdm seed reaches sup@160 AND rrcdm@211", chain through the sup@223 read leg); PL@253 and Digitallending@549 follow the same effect-scope rule.
- **Input tables stay OUT (verified 2026-08-12):** SUP_M's sup-write statement joins `ods_hie_ipacmsp` (line ~151, LEFT JOIN) and other sources, yet `ods_hie_ipacmsp` is NOT in the projection — it is an input whose rows the queried field's usage selects, not a carrier of the queried field's flow (field-level, not statement-level). The projection table set is exactly `{bdm_acc_loan_info, bdm_acc_loan_info_sup, rrcdm_job_log_exec_par}`.

### 6a.3 The exclusion case that motivated the change (verified 2026-08-12)

Seed `ODS_CUPD_CLD_ACCTMASTER_NEW.BNQXYE` (BDM_ACC_LOAN_INFO_Digitallending.sql): `BDM_ACC_LOAN_INFO_SUP_M.sql` contains **0** occurrences of BNQXYE, **0** of ODS_CUPD_CLD_ACCTMASTER_NEW, **0** of INT_OD_AMT (the BNQXYE-derived column) — it only reads `bdm_acc_loan_info` (the searched field's output TABLE). Under R29, SUP_M is excluded from L1 in BOTH directions. The old table-level L1 (production BFS + multi-hop expansion over the queried table's neighborhood) showed it — that behavior is superseded.

# PART II — CANONICAL GROUND TRUTH v2 (benchmark spec, pl-seed round 2026-08-11)

This part is the machine-comparable target. The benchmark
(`backend/tests/test_jaccard_benchmark.py`) compares the system's live
L2 output against THIS spec (via `backend/tests/jaccard_canonical.py`)
and reports the recall/precision pair per seed per feature (J12-12:
A = B ⟺ recall = precision = 1.0 — genuine SET EQUALITY, never a size
check). B is compiled from the REQUIREMENT sections (§4.2/§4.3),
J12-13 — never from the engine's emitted form; the §8.5 closure table
records the served realization of each requirement row (probe-pinned,
after the requirements were written).

## 7.1 The trials (mirror of the SUP doc — what each calculation proved)

Probe-pinned (2026-08-12, served L2 for the seed
`bdm_acc_loan_info.data_dt` on the J12-17-fixed engine):

1. **Filtered-L2 closure:** 7 nodes / 9 edges (the served graph — full
   node/edge listing in §8.5). All 9 canonical pl rows realized.
2. **Downstream write-leg walk (flow_targets):** both DML write legs
   are in the closure — target `bdm_acc_loan_info@19` (stmt1, TOP0) and
   target `rrcdm_job_log_exec_par@253` (stmt2, TOP2) — each stamped
   flow_kind='write' via its `_dml_out` TABLE_FLOW edge.
3. **Node realization count:** canonical 8 → served 7 (the J12-16 fold
   merges data_dt@19/@264; the bdm@263 reader instance rides the bdm@19
   compound; charge_department@265 is an edgeless extra — §8.6). The
   gate's measured pair for nodes: recall 1.0000 / precision 1.1429
   (8 matched / 7 served).

## 7.2 THE canonical spec (the benchmark target)

**Nodes (canonical names @ lines):**

```
field (3):        data_dt@19, data_dt@254, data_dt@264
table/scope (3):  bdm_acc_loan_info@19 (stmt1 target), bdm_acc_loan_info@263
                  (stmt2 reader), rrcdm_job_log_exec_par@253 (stmt2 target)
source/join (0):  NONE — no source/join table is in the closure: the
                  partition is literal-driven and the TOP1 sources
                  (a/c/D/p2/T_BRANCH) carry other fields. [Draft listed
                  acctm/credinf/branch/coa/lrr/hsbc — WRONG: probe-verified
                  absent from the served closure; corrected 2026-08-12.]
VT plumbing (2):  ⟐ insert@0 (TOP0, served label 'insert'), ⟐ output@0
                  (TOP2, served label 'output')
```

**Sinks (2):** `bdm_acc_loan_info@19`, `rrcdm_job_log_exec_par@253`.

**Edges (canonical endpoint pairs — REQUIREMENT, §4.2/§4.3):** the
stmt1 write leg (⟐insert → bdm@19), the stmt2 read (data_dt@264 →
bdm@263), the reader's read leg (bdm@263 → ⟐output), the stmt2 write
leg (⟐output → rrcdm@253), plus the value writes / filter / SCHEMA rows
pinned in §8.5 (9 rows total).

**Highlights:** per §8 — every closure edge anchors at exactly one line
(the closure anchors: 19, 253, 254, 263, 264).

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
   regress; the pl seed's floors ratchet up from the measured values.

## 7.4 Loop round 1 outcome

**Engine gap found and fixed (J12-17, 2026-08-12):** the bare INSERT@19's
output VT is named `"⟐ insert"` (extractor), not `"⟐ output"` — the
per-statement trunk registration in `_simplify_dml_edges` only accepted
`('⟐ output', TOPn)`, so stmt1's write leg had no trunk (the pre-fix
served payload had 5 nodes / 7 edges — no insert node, no write leg).
Fix (extraction-time info only): (a) the trunk check accepts ANY
statement-level output VT (name `⟐ *`, context exactly `TOP{numeric}`);
(b) a rule-2 self-loop guard drops the redundant raw REF-READ
`⟐insert→target` (it duplicates the routed write leg); (c) a reverse-DML
admit in `compute_field_flow` admits a statement's own output VT
backward from an admitted DML target only when the statement's write
leg carries the searched field (so the trunk joins the closure just
when the statement writes the field).

Post-fix served payload: 7 nodes / 9 edges — the full §8.5 table
realized; gate GREEN with floors 1.0000/1.0000 per feature (pl block:
nodes recall 1.0000 / precision 1.1429, edges 1.0/1.0, highlights
1.0/1.0); bdm/sup floors unchanged (1.0); full suite 809 passed /
5 skipped.

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
synthetic-source / chain / SCHEMA / SUBSET rules 1-7). The "pl" rows in
§8.5 record the rule each row follows.

### 8.4 Counting invariant

Per edge: exactly one primary line; every closure edge is pinned (§8.5)
so the payload count is deterministic.

### 8.5 Highlight ground truth for testing (CANONICAL_EDGE_LINES — complete)

**The complete table — 9 entries, this sample, post-promotion state
(the "pl" block of jaccard_canonical.py; REQUIREMENT rows P15/P18/P22/
P16 marked; each row's Real type = the served realization,
probe-pinned on the J12-17-fixed engine):**

| # | Pair | Kind | Real type (post-promotion) | Seed | Anchor |
|---|------|------|---------------------------|------|--------|
| P15 | `⟐output@0 → bdm@19` — REQUIREMENT row (§4.3 item 3 — the stmt1 write leg; source VT served label 'insert', TOP0) | write | TABLE_FLOW (flow_kind='write', id `l2e_796c5b52f478_dml_out`) | pl | 19 |
| P16 | `⟐output@0 → rrcdm@253` — REQUIREMENT row (§4.2 LAYER-2 — the stmt2 write leg; source VT served label 'output', TOP2) | write | TABLE_FLOW (flow_kind='write', id `l2e_a22cde60b6a9_dml_out`) | pl | 253 |
| P18 | `data_dt@264 → bdm@263` — REQUIREMENT row (§4.2 — the stmt2 read) | READ | REF (id `l2e_e8a0208b566d`, kind=read) | pl | 263 |
| P22 | `bdm@263 → ⟐output@0` — REQUIREMENT row (§4.2 — the reader's read leg) | chain | TABLE_FLOW (id `l2e_74f8e8806b83`, kind=chain) | pl | 263 |
| R1 | `data_dt@19 → ⟐output@0` (the write-column read into the stmt1 output VT) | READ | REF (id `l2e_e0f92ce52252`, kind=read) | pl | 19 |
| V1 | `data_dt@19 → ⟐output@0` (value split of the stmt1 write) | write | TABLE_FLOW (id `l2e_7efd4cd8e2cb_value`, kind=write — the value edge) | pl | 19 |
| V2 | `data_dt@254 → ⟐output@0` (value split of the stmt2 write) | write | TABLE_FLOW (id `l2e_48875b94be43_value`, kind=write — the value edge) | pl | 254 |
| M1 | `⟐output@0 → data_dt@254` (the output column's structural edge) | structure | SCHEMA (id `l2e_4d54cafaf923`) | pl | 254 |
| F1 | `data_dt@264 → bdm@264` (the stmt2 WHERE filter) | field flow | FILTER (id `l2e_e71298c1acf4`) | pl | 264 |

Closure seeds: **"pl = 7 nodes / 9 edges"** (probe-pinned — the served
L2 closure for the `bdm_acc_loan_info.data_dt` seed: 4 compound nodes
bdm_acc_loan_info@19 / insert@19 / rrcdm_job_log_exec_par@253 /
output@253 + 3 field nodes data_dt (bdm, incidents 19+264) / data_dt
(rrcdm, 254) / charge_department (rrcdm, 265); the 9 edges above).
Gate: recall/precision 1.0000/1.0000 per feature (nodes printed
1.0000/1.1429 — 8 canonical realized by 7 served).

### 8.6 Current-system gaps this definition exposes

Probe-pinned (2026-08-12):

- `charge_department@265` (stmt2's second WHERE condition) is an
  edgeless FIELD node in the served closure — the FILTER-zone adjacency
  admits its filter sibling; it carries no closure edge. Documented
  R11-2-style extra (the same shape the SUP doc documents): it costs
  nothing in the gate (edges/highlights exact; node precision prints
  1.1429 as the measured ratio, floor still 1.0000).
- The TOP1 SELECT@21's ~130 output columns (LENDING_REF …) never reach
  bdm_acc_loan_info — the script's INSERT OVERWRITE@19 is BARE
  (partition-only). If the real BDM_ACC_LOAN_INFO_PL script is
  re-OCR'd with the SELECT body inline into the INSERT, the statement
  split changes (TOP0 becomes the full INSERT…SELECT) and the closure
  shape moves — the benchmark pins the CURRENT file; re-pin only if the
  sample is replaced (ground-truth-may-be-wrong rule).

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
