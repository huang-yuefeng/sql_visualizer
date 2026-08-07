# Ground Truth — BDM_ACC_LOAN_INFO_SUP_M.sql

Hand-verified data flow of `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_SUP_M.sql`
(226 lines). This is the reference for future work: every extractor / graph /
highlight change must preserve these flows. All facts below were verified by
running the live extraction (v3.3.145, 2026-08-07) and by reading the SQL.

---

## 1. Script structure

```
stmt1 (L9-208):  WITH rollover_loan_info (L9-63), loan_final (L64-159)
                 INSERT OVERWRITE bdm_acc_loan_info_sup
                 PARTITION(data_dt='$(load_date)', CHARGE_DEPARTMENT)   (L160)
stmt2 (L211-225): INSERT INTO rrcdm_job_log_exec_par
                  SELECT '$(load_date)' AS data_dt, ..., COUNT(1)
                  FROM bdm_acc_loan_info_sup WHERE data_dt='$(load_date)' (L225)
```

Global extraction facts: **253 variables, 649 dependencies, 14 ALIAS edges,
parse_errors = []** (verified twice, deterministic).

---

## 2. Table-level flow

```
bdm_acc_loan_info ─────────────► rollover_loan_info   (CTE1, L9)
  read L16 (bare), L29 (as p1)
ods_hub_lsacmsp ───────────────► rollover_loan_info
  read L33 (inside derived p2)
bdm_evt_loan_trans ────────────► rollover_loan_info
  read L52 (NOT IN subquery, alias a)

bdm_acc_loan_info ─────────────► loan_final           (CTE2, L64)
  read L84 (as p1)
bdm_gdc_label_fin ─────────────► loan_final
  read L89 (via accu), L93 (via t)
ods_cdp_gdc_acct_migrate_to_diff_branches ─► loan_final
  read L101 (via branch), L103 (via a)
ods_hub_lsacmsp ───────────────► loan_final
  read L33 (via derived p2)
ods_hub_ssclmtp ───────────────► loan_final
  read L118 (as p3)
ods_hie_ipblmsp ───────────────► loan_final
  read L132 (as a)
ods_hie_ipdcmsp ───────────────► loan_final
  read L133 (as b)
ods_hie_ippdcpp ───────────────► loan_final
  read L137 (as c)
ods_hie_ipacmsp ───────────────► loan_final
  read L151 (as p5)
rollover_loan_info (CTE1) ─────► loan_final
  read L155 (as p6)

loan_final (CTE2) ─────────────► bdm_acc_loan_info_sup   (INSERT OVERWRITE L160)
  read L198 (as p1)
bdm_acc_loan_info_sup ─────────► bdm_acc_loan_info_sup
  read L199 (as p2 — yesterday's own data, self-join)
bdm_sys_acc_loan_info ─────────► bdm_acc_loan_info_sup
  read L204 (as p3)

bdm_acc_loan_info_sup ─────────► rrcdm_job_log_exec_par  (INSERT INTO L211, job log)
  read L223 (bare)
```

## 3. Alias def-line map (I1 semantics — first token of the defining clause)

```
rollover_loan_info (L9-63):
  p1 = bdm_acc_loan_info                 (L29, inside the DISTINCT subquery)
  p2 = derived over ods_hub_lsacmsp      (L33-40)
  a  = bdm_evt_loan_trans                (L52, NOT IN subquery)

loan_final (L64-159):
  p1    = bdm_acc_loan_info              (L84)
  accu  = derived over bdm_gdc_label_fin (L85-94),  t = bdm_gdc_label_fin (L93, MAX subq)
  branch= derived over ods_cdp_gdc_acct_migrate_to_diff_branches (L96-104),  a = same (L103)
  p2    = derived over ods_hub_lsacmsp   (L106-116)
  p3    = ods_hub_ssclmtp                (L118)
  p4    = derived over ods_hie_ipblmsp a / ods_hie_ipdcmsp b / ods_hie_ippdcpp c (L128-149)
  p5    = ods_hie_ipacmsp                (L151)
  p6    = rollover_loan_info (CTE1)      (L155)

stmt1 main SELECT:
  p1 = loan_final                        (L198)
  p2 = bdm_acc_loan_info_sup (yesterday) (L199)
  p3 = bdm_sys_acc_loan_info             (L204)
```

---

## 4. Field ground truth — bdm_acc_loan_info.data_dt

### 4.1 Occurrence lines (the "touch points")

```
L18   data_dt = '$(load_date)'            read, CTE1 WHERE, bare → bdm_acc_loan_info (L16)
L43   SUBSTR(p1.data_dt,1,7) = ...        read, inner subq WHERE, p1 = bdm_acc_loan_info (L29)
L158  p1.data_dt = '$(load_date)'         read, CTE2 WHERE, p1 = bdm_acc_loan_info (L84)
L160  PARTITION(data_dt='$(load_date)')   write, stmt1 target partition
```

NOT this field (belongs to other tables — negative proof):

```
L55   SUBSTR(a.data_dt,1,7)   → a = bdm_evt_loan_trans (L52)
L93   data_dt = (SELECT MAX(t.data_dt) ...)  → bdm_gdc_label_fin (L89) / t (L93)
L202  p2.data_dt = DATEADD(...) → bdm_acc_loan_info_sup (L199) — SELF-JOIN of the target
L213  '$(load_date)' AS data_dt → literal output column of stmt2
L225  data_dt = '$(load_date)'  → bdm_acc_loan_info_sup (L223) — stmt2 read
```

### 4.2 Downstream layer-by-layer (targets of targets)

```
LAYER 0 — the field (4 occurrences):  L18, L43, L158 (reads), L160 (write)

LAYER 1 — direct targets:
  L18  ──► rollover_loan_info (CTE1)     ← the WHERE constrains CTE1's input rows
  L43  ──► ⟐ subq (inner derived L19-62) ← the SUBSTR filter constrains the IN subquery
  L158 ──► loan_final (CTE2)             ← the WHERE constrains CTE2's input rows
  L160 ──► bdm_acc_loan_info_sup (L160)  ← partition write lands here

LAYER 2 — targets of layer 1:
  rollover_loan_info  ──► loan_final      (consumed as p6@155)
  ⟐ subq              ──► rollover_loan_info  (the IN(...) subquery feeds CTE1)
  loan_final          ──► bdm_acc_loan_info_sup (consumed as p1@198 → INSERT L160)
  bdm_acc_loan_info_sup ─► bdm_acc_loan_info_sup (self-join as p2@199, yesterday)
  bdm_acc_loan_info_sup ─► rrcdm_job_log_exec_par (read L223 → INSERT L211)

LAYER 3 — final targets (sinks):
  bdm_acc_loan_info_sup    (partition data_dt written; also self-read for yesterday)
  rrcdm_job_log_exec_par   (job log: COUNT(1) of the sup table)
```

Semantic closure: **10 nodes** (4 field occurrences + bdm_acc_loan_info +
rollover_loan_info + ⟐ subq + loan_final + bdm_acc_loan_info_sup +
rrcdm_job_log_exec_par), **2 final sinks**.

### 4.3 Edge inventory — what the graph has vs. what it must have

Present (10, verified by probe):

```
SUBSET  data_dt@18            → bdm_acc_loan_info@16     (field → its table)
SUBSET  bdm_acc_loan_info@16  → rollover_loan_info@9     (CTE1 reads the table)
FILTER  p1.data_dt@43         → ⟐ subq@0                 (L43 filter in subq)
TABLE_FLOW p1@29              → ⟐ subq@0                 (the read itself)
TABLE_FLOW ⟐ subq@0           → ⟐ subq1@0                (IN-subquery plumbing)
TABLE_FLOW ⟐ subq1@0          → rollover_loan_info@9     (feeds CTE1)
FILTER  p1.data_dt@158        → loan_final@64            (L158 filter in CTE2)
TABLE_FLOW p1@84              → loan_final@64            (the read itself)
ALIAS   rollover_loan_info@9  → p6@155                   (CTE1 consumed in CTE2)
TABLE_FLOW p6@155             → loan_final@64
ALIAS   loan_final@64         → p1@198                   (CTE2 consumed in stmt1)
TABLE_FLOW loan_final@64      → ⟐ output@0               (stmt1 output)
ALIAS   bdm_acc_loan_info_sup@160 → p2@199               (self-join alias)
SUBSET  data_dt@160           → bdm_acc_loan_info_sup@160 (partition write)
```

MISSING (4, all verified absent by probe — the graph defects):

```
1. p1.data_dt@43  → bdm_acc_loan_info@29   read edge field→its alias table
   (only SCHEMA p1@29→p1.data_dt@43 exists — ownership, wrong direction)
2. p1.data_dt@158 → bdm_acc_loan_info@84   read edge field→its alias table
3. ⟐ output@0(TOP0) → bdm_acc_loan_info_sup@160  table-level DML edge
   (stmt1's output VT is a dead end; DML exists only as 15 field-level edges
   + direct TABLE_FLOW p1@198/p2@199/p3@204 → sup)
4. bdm_acc_loan_info_sup@160 → bdm_acc_loan_info_sup@223  cross-statement
   write→read link (stmt2 read has ZERO incident edges — stmt2 is an island)
```

Cross-scope SCHEMA contamination (the I2 finding, visible in the same probe):
`SCHEMA` edges attach **every** `p1.*` field to **every** p1 alias across all
scopes — `p1@29` (rollover's inner alias) owns `p1.data_dt@158`,
`p1.issue_dt@181`, `p1.internal_key@162` … fields read in other scopes.
`p1.data_dt@43` has three SCHEMA parents (p1@29, p1@84, p1@198).

### 4.4 The two calculations compared (and why both are wrong)

```
Run 1 — filter_by_field_flow (the L2 view):   11 nodes / 5 edges
Run 2 — downstream BFS on the full graph:     14 nodes / 10 edges

Both agree (and are RIGHT) on: the 4 touch lines [18,43,158,160] and the
4 layer-1 targets.

Run 1 is right that the source tables belong in a field query, but shows
bdm_acc_loan_info@29/@84 as DISCONNECTED stubs (no field→table edge — I2).
Run 2 correctly extends the downstream chain (subq→subq1→CTE1,
CTE1→p6→loan_final, loan_final→p1@198/output, sup→p2@199) but is blind to
the source tables and dead-ends before stmt2.

NEITHER reaches rrcdm_job_log_exec_par — impossible, because missing
edge #4 (write→read) disconnects stmt2 entirely.

VERDICT: both wrong (under-connected). Once the 4 missing edge types exist,
both calculations converge to the 10-node / 2-sink ground truth above.
```

---

## 5. Highlight ground truth

### 5.1 The field's own lines — current tool output is CORRECT

Verified byte-exact (live API, 2026-08-06): `[[18,18],[43,43],[158,158],[160,160]]`

```
L18   data_dt = '$(load_date)'             ← bdm_acc_loan_info read (CTE1)
L43   SUBSTR(p1.data_dt,1,7) = ...         ← p1.data_dt read (inner subq)
L158  p1.data_dt = '$(load_date)'          ← p1.data_dt read (CTE2)
L160  PARTITION(data_dt='$(load_date)')    ← partition write (stmt1 target)
```

Negative proof — lines correctly NOT highlighted:

```
L55   a.data_dt    → bdm_evt_loan_trans    (other table)
L93   data_dt/t.data_dt → bdm_gdc_label_fin (other table)
L202  p2.data_dt   → bdm_acc_loan_info_sup (propagated field, target's own)
L213  data_dt      → literal output column (propagated field, target's own)
L225  data_dt      → bdm_acc_loan_info_sup (propagated field, target's own)
```

### 5.2 The propagated field (lineage view) — the gap

After the L160 write, `sup.data_dt` carries the same field lineage. Its
occurrences (verified via `bdm_acc_loan_info_sup.data_dt` closure — 6 nodes /
2 edges, field lines [160, 202, 213]):

```
L202  p2.data_dt = DATEADD(...)   read of the propagated field (self-join)   ✓ has a var
L213  '$(load_date)' AS data_dt   stmt2 output column                        ✓ has a var
L225  data_dt = '$(load_date)'    stmt2 WHERE read                        ✗ NO VAR AT ALL
```

**Defect 5:** the L225 read is not extracted — no variable exists at line 225
(the stmt2 WHERE read of `bdm_acc_loan_info_sup.data_dt` is lost; only the
SELECT literal at L213 is extracted). A complete lineage highlight would be
`[18, 43, 158, 160, 202, 213, 225]`; the tool can currently express
`[18, 43, 158, 160]` (bdm_acc_loan_info) and `[160, 202, 213]`
(bdm_acc_loan_info_sup) but can never show 225.

### 5.3 Highlight semantics (what the ground truth means)

- The tool highlights **field occurrence lines** only (column vars), not the
  table `FROM` lines (L16/L29/L84) — correct by design.
- Field identity is per-table: `bdm_acc_loan_info.data_dt` = [18,43,158,160];
  `bdm_acc_loan_info_sup.data_dt` = [160,202,213]. A *lineage* mode that
  follows the write would merge them into [18,43,158,160,202,213,(225)].
- Literal producers (`'$(load_date)'` at L160/L213) are not traced — by design.

---

## 6. Test contract (what a regression test must pin)

```
1. parse_errors == [] ; 253 vars ; 649 deps ; 14 ALIAS edges (exact pairs)
2. alias def lines: p1@29, p2@40, a@52, p1@84, t@93, accu@94, a@103,
   branch@104, p2@116, p3@118, a@132, b@133, c@137, p4@149, p5@151,
   p6@155, p1@198, p2@199, p3@204
3. bdm_acc_loan_info.data_dt closure (L2): 11 nodes / 5 edges, field lines
   [18, 43, 158, 160] — current engine output (deterministic, verified twice)
4. downstream closure: 14 nodes / 10 edges (layer-by-layer walk)
5. THE GROUND TRUTH: 10 semantic nodes, 2 sinks (bdm_acc_loan_info_sup,
   rrcdm_job_log_exec_par), 14 edges = 10 present + 4 MISSING (documented in 4.3)
6. highlights [[18,18],[43,43],[158,158],[160,160]] (byte-exact)
7. propagated field: sup.data_dt lines [160, 202, 213]; L225 has no var
   (Defect 5) — pin this as a known gap until fixed
```

Status: analysis only — no source changes. The 4 missing edge types (4.3) and
Defect 5 (5.2) are the known defects future work must address.

---

# PART II — CANONICAL GROUND TRUTH v2 (benchmark spec, consolidated 2026-08-07)

This part is the machine-comparable target. The benchmark
(`backend/tests/test_ground_truth_benchmark.py`) compares the system's live L2
output against THIS spec and reports a structured diff. Every solution update
must re-run the benchmark (the loop protocol in §7.3).

## 7.1 The three trials — what each proved

```
Trial 1 — filter_by_field_flow (the L2 search view):  11 nodes / 5 edges
  RIGHT: touch lines [18,43,158,160]; layer-1 targets (rollover@9, ⟐subq,
         loan_final@64, sup@160); highlight lines.
  WRONG: bdm@29 / bdm@84 are DISCONNECTED stubs (no field→table edge — missing
         #1/#2); stmt2 unreachable (no cross-statement link — missing #4).

Trial 2 — downstream BFS on the full graph:           14 nodes / 10 edges
  RIGHT: the downstream chain — subq→subq1→rollover, rollover→p6→loan_final,
         loan_final→p1@198, sup→p2@199 self-join.
  WRONG: blind to the SOURCE table reads; dead-ends before stmt2.

Trial 3 — source_tables-driven closure (no edges):    13 nodes / 14 edges / 2 sinks
  RIGHT: the full closure including rrcdm_job_log_exec_par@211; covers all 4
         missing-edge semantics (#1/#2 read edges, #3 output→target, #4
         cross-statement write→read) from extraction-time info alone.
  LIMITS: prototype only, validated on this one script.
```

**Where all three agree (the stable core — must never change without evidence):**
touch lines [18, 43, 158, 160]; highlight lines; the closure's TABLE SET; the
4 missing-edge semantics; Defect 5 (L225 has no var).

## 7.2 THE canonical spec (the benchmark target)

**Nodes (13, canonical names @ lines):**

```
field (4):        data_dt@18, p1.data_dt@43, p1.data_dt@158, data_dt@160
table/scope (7):  bdm_acc_loan_info@16, p1@29, p1@84, rollover_loan_info@9,
                  loan_final@64, bdm_acc_loan_info_sup@160, rrcdm_job_log_exec_par@211
VT plumbing (2):  ⟐ subq@0, ⟐ subq1@0
```

Normalization: `p1@29` ≡ `bdm_acc_loan_info@29` (I1 semantics — alias read at
the same line = same table). Both graph renderings must map to the same
canonical node for comparison purposes.

**Sinks (2):** `bdm_acc_loan_info_sup@160`, `rrcdm_job_log_exec_par@211`.

**Edges (14 semantic — the graph's 10 present + 4 missing; each must be
covered by at least one system edge linking the canonical endpoints):**

```
present (10):
  SUBSET  data_dt@18            → bdm_acc_loan_info@16
  SUBSET  bdm_acc_loan_info@16  → rollover_loan_info@9
  FILTER  p1.data_dt@43         → ⟐ subq@0
  TABLE_FLOW p1@29              → ⟐ subq@0
  TABLE_FLOW ⟐ subq@0           → ⟐ subq1@0
  TABLE_FLOW ⟐ subq1@0          → rollover_loan_info@9
  FILTER  p1.data_dt@158        → loan_final@64
  TABLE_FLOW p1@84              → loan_final@64
  ALIAS   rollover_loan_info@9  → p6@155   (+ TABLE_FLOW p6@155 → loan_final@64)
  ALIAS   loan_final@64         → p1@198   (+ TABLE_FLOW p1@198 → sup@160,
                                          TABLE_FLOW p2@199 → sup@160 self-join,
                                          TABLE_FLOW p3@204 → sup@160)
  SUBSET  data_dt@160           → bdm_acc_loan_info_sup@160

missing (4 — the fix target; proposed system types in brackets):
  1. p1.data_dt@43  → p1@29        [SUBSET — mirrors the unqualified data_dt@18→bdm@16]
  2. p1.data_dt@158 → p1@84        [SUBSET]
  3. ⟐ output@0     → bdm_acc_loan_info_sup@160   [DML or TABLE_FLOW — output VT→target]
  4. bdm_acc_loan_info_sup@160 → bdm_acc_loan_info_sup@223 → rrcdm_job_log_exec_par@211
                                    [TABLE_FLOW — cross-statement write→read]
```

Edge-type tolerance for coverage: any of {TABLE_FLOW, SUBSET, ALIAS, DML,
REF} linking the canonical endpoints covers the semantic edge; the benchmark
reports actual types so type mismatches are visible, but does not fail on them
(types are a rendering decision; closure connectivity is the contract).

**Highlights:**

```
field bdm_acc_loan_info.data_dt:  [[18,18],[43,43],[158,158],[160,160]]  (byte-exact)
propagated bdm_acc_loan_info_sup.data_dt: [160, 202, 213]  (L225 = KNOWN GAP,
    Defect 5 — extractor never creates a var at L225; benchmark marks it
    "known gap", not a fail, until the extractor is fixed)
```

## 7.3 Benchmark protocol (the loop)

1. Run `docker exec gps-sql-backend sh -c 'cd /app/backend && python3 -m
   pytest tests/test_ground_truth_benchmark.py -v'` → structured diff
   (missing/extra nodes, missing/extra edges, sinks, highlights, propagated).
2. Classify each diff line:
   - (a) solution defect → fix the solution (build on extraction-time info —
     no patch solutions / no reconstruction from rendered output);
   - (b) ground-truth wrong → update THIS spec, with evidence (which trial
     proved it, why the old entry was wrong);
   - (c) known gap → keep the marker until its root cause is fixed.
3. Re-run the benchmark. Repeat until MATCH (empty diff).
4. The benchmark is the regression gate: every solution update re-runs it.
   Ground truth and solution converge by alternating these two loops.

Convergence prediction (§4.4, to verify): once the 4 missing edges exist,
Trial 1 and Trial 2 both converge to this 13-node / 14-edge / 2-sink spec.
Trial 3 (source_tables closure) is the oracle that checks them.
