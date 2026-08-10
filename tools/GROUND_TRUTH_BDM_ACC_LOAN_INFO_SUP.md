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

Global extraction facts: **253 variables, 781 dependencies, 14 ALIAS edges,
parse_errors = []** (verified twice, deterministic; deps count is a SNAPSHOT —
v3.3.147: 781 = 737 + 44 (the W-iteration REF/READ expansion — bare-column
reads and the pair-18 L225 read; the pair-2 chain bridge is re-typed, not
added).

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

### 4.4 The two calculations compared (and why both were wrong)

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

VERDICT (then): both wrong (under-connected). Once the 4 missing edge types
exist, both calculations converge to the 10-node / 2-sink ground truth.

VERDICT (v3.3.146, verified — the prediction came true): the 4 edge types
were emitted (Phase 4d READ, 1c-extra2, 1c-cross WRITE_READ, 1c-direct,
1c-self — §7.4) and the L2 walker was fixed (joint fixpoint + forward-only
TABLE_FLOW in compute_field_flow). The benchmark now reports the exact
canonical closure: 13 canonical nodes + allowed intermediates, 16/16
canonical edge pairs, 2/2 sinks, byte-exact highlights [18,43,158,160] and
propagated [160,202,213].
```

---

## 5. Highlight ground truth

> **⚠️ SUPERSEDED (2026-08-10, user ruling):** §5 (field-occurrence
> highlight lines) and the §7.2 "Highlights" block are superseded by the
> formal definition in **§8 — Highlight is per-edge (edge = one data flow),
> there is no field highlight**. The line sets here remain useful only as
> fallback candidates for edge spans (§8.3.2). Kept for the audit trail.

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
L225  (removed from this list 2026-08-10 — the stmt2 WHERE read now
       highlights: pair 18, REF/read @223 + FILTER @225, §8.5)
```

### 5.2 The propagated field (lineage view) — the gap

After the L160 write, `sup.data_dt` carries the same field lineage. Its
occurrences (verified via `bdm_acc_loan_info_sup.data_dt` closure — 6 nodes /
2 edges, field lines [160, 202, 213]):

```
L202  p2.data_dt = DATEADD(...)   read of the propagated field (self-join)   ✓ has a var
L213  '$(load_date)' AS data_dt   stmt2 output column                        ✓ has a var
L225  data_dt = '$(load_date)'    stmt2 WHERE read                        ✓ has a var (W2, pair 18)
```

**Defect 5 — RESOLVED (W2, token-run extension, bug list §v3.3.147 addendum 2;
probe-verified 2026-08-10):** the L225 read IS extracted — a var exists at
line 225 (the stmt2 WHERE read of `bdm_acc_loan_info_sup.data_dt`). The
complete lineage highlight is `[18, 43, 158, 160, 202, 213, 225]`:
`[18, 43, 158, 160]` (bdm_acc_loan_info) and `[160, 202, 213, 225]`
(bdm_acc_loan_info_sup) — pair 18 (REF/read, anchor 223) plus its FILTER
companion at 225, §8.5.

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
7. propagated field: sup.data_dt lines [160, 202, 213, 225] (W2: L225 now
   has a var — pair 18, REF/read anchor 223, §8.5)
```

Status: analysis only — no source changes. The 4 missing edge types (4.3)
remain the known defect future work must address; Defect 5 (5.2) is RESOLVED
(W2, 2026-08-10).

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
4 missing-edge semantics; Defect 5 RESOLVED (W2): L225 now has a var (pair 18, §8.5).

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

**Edges (16 canonical endpoint pairs — 12 present-chain + 4 that were
missing; ALL COVERED as of v3.3.146, verified by the benchmark. Each pair
must be covered by at least one system edge linking the canonical
endpoints):**

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

missing (4 — FIXED in v3.3.146 by the loop round 1; emission phases in §7.4):
  1. p1.data_dt@43  → p1@29        [SUBSET op=READ — Phase 4d, own-scope alias]
  2. p1.data_dt@158 → p1@84        [SUBSET op=READ — Phase 4d, own-scope alias]
  3. ⟐ output@0     → bdm_acc_loan_info_sup@160   [TABLE_FLOW op=INSERT — 1c-extra2]
  4. bdm_acc_loan_info_sup@160 → bdm_acc_loan_info_sup@223 → rrcdm_job_log_exec_par@211
                                    [DML op=WRITE_READ — 1c-cross, write→read]
```

Edge-type tolerance for coverage: any of {TABLE_FLOW, SUBSET, ALIAS, DML,
REF} linking the canonical endpoints covers the semantic edge; the benchmark
reports actual types so type mismatches are visible, but does not fail on them
(types are a rendering decision; closure connectivity is the contract).

**Highlights:**

> **⚠️ SUPERSEDED (2026-08-10, user ruling):** the field-occurrence
> highlight is removed by the formal definition in §8 (edge-driven
> highlights only). These line sets are kept as fallback candidates
> (§8.3.2) and as the audit trail of what was once asserted.

```
field bdm_acc_loan_info.data_dt:  [[18,18],[43,43],[158,158],[160,160]]  (byte-exact)
propagated bdm_acc_loan_info_sup.data_dt: [160, 202, 213, 225]  (W2: the
    extractor fix — bug list §v3.3.147 addendum 2 — creates the var at L225;
    the KNOWN GAP marker is removed; pair 18 is live, §8.5)
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
   - (c) known gap → keep the marker until its root cause is fixed (pair 18's
     marker removed 2026-08-10 — Defect 5 fixed by W2).
3. Re-run the benchmark. Repeat until MATCH (empty diff).
4. The benchmark is the regression gate: every solution update re-runs it.
   Ground truth and solution converge by alternating these two loops.

Convergence prediction (§4.4, to verify): once the 4 missing edges exist,
Trial 1 and Trial 2 both converge to this 13-node / 14-edge / 2-sink spec.
Trial 3 (source_tables closure) is the oracle that checks them.

## 7.4 Loop round 1 outcome — v3.3.146 (2026-08-07, team iteration + main-session audit)

Verdict of the iteration: **converged**. Benchmark went 3/6 → 5/6 (closure
semantics 100% canonical); the 6th test's failure was a stale SNAPSHOT pin
(649 deps), updated to 737 after independent verification → 6/6.

### Solution changes (commit da6e18f — all audited, extraction-time info only)

```
dependency_graph.py:
  Phase 4d      SUBSET op=READ — qualified column → ITS OWN-SCOPE alias table
                (context-equality guard → I2 cross-scope pairs impossible;
                verified: 83 edges, 0 cross-scope)
  1c-extra2     TABLE_FLOW op=INSERT — statement output VT → its DML target
                (per-context, len(out_vts)==1 guard; TOP0→sup@160, TOP1→rrcdm@211)
  1c-cross      DML op=WRITE_READ — cross-statement write→read by canonical
                table name (runs BEFORE Phase 7/8 → union-find sees the link)
  1c-direct     TABLE_FLOW — CTE output → its reader CTE / statement DML target
                (rollover@9→loan_final@64, loan_final@64→sup@160)
  1c-self       TABLE_FLOW SELF_JOIN self-loop — DML target read by its own
                statement (sup@160, from the p2@199 self-join)
  REMOVED       Phase-7 SUBSET BRIDGE rrcdm@211→bdm_sys_acc_loan_info@204 —
                superseded by WRITE_READ (it was a compensation for the
                missing cross-statement link)

lineage.py compute_field_flow:
  Joint fixpoint — expansion and identity-admission rounds interleave until
  stable (identity-admitted nodes can now fire ALIAS/TABLE_FLOW/DML edges)
  TABLE_FLOW clause — forward-only: (a) table-like source whose physical
  identity is in the chain; (b) VT whose context is ancestor-or-equal of a
  visited field var's context (admits ⟐subq1@0, ⟐output@0)

test_edge_validity.py: SUBSET op=READ exempted from the "synthetic bridge"
assertion (Phase 4d read attribution is not a bridge) — narrow, documented.
```

### Audit record (main session — independent verification of every claim)

All verified by probe (tools/probe_new_edges.py, fresh extraction): deps 737
= 649 + 89 − 1; 83 READ pairs include both canonical (#1/#2) and ZERO
cross-scope pairs; the two output-VT edges come from DISTINCT per-statement
VTs (TOP0/TOP1 — no shared-var collision); exactly one WRITE_READ in the
correct direction; Phase-7 bridge truly gone; self-loop present; 1c-direct
edges present. Full suite: 647 passed / 1 failed (only the stale pin) — no
regression in the other tests.

### Open concerns (not blockers — bug-list §v3.3.146)

```
1. 1c-cross emits write→read WITHOUT a statement-ORDER check — a table read
   in an EARLIER statement and written in a LATER one would get a reversed-
   time edge. Harmless here (2 statements, read is later); refine with a
   TOP-index comparison when other scripts exercise it.
2. 1c-self has a vacuous guard (`ek in seen_edges` can never be true —
   self-loops are forbidden by _add_edge) — dead code, harmless.
3. Walker clause (b) scans node_map.values() per candidate TABLE_FLOW edge
   (O(V) per check) — perf risk on very large scripts; memoize visited-field
   contexts when needed.
4. 1c-direct duplicates the ALIAS+TABLE_FLOW consumption chains — accepted
   by design so canonical endpoint keys pair exactly; benign redundancy.
```

### Benchmark contract update (accepted — main session)

test_global_sanity deps pin 649 → 737 with a snapshot-semantics note
(deltas are findings to classify, not automatic failures). The count is
NOT a semantic invariant of the closure spec (§7.2 defines nodes/edges/
sinks/highlights only).

---

## 8. Highlight — formal definition (v3.3.147, user ruling 2026-08-10)

> This section is the AUTHORITATIVE definition of the highlight feature.
> It supersedes §5 and the §7.2 "Highlights" block (marked ⚠️ there).
> No implementation happened when this was written — the definition is
> the contract for the next iteration round.

### 8.1 Feature definition

The highlight feature visualizes, **for each data flow (L2 edge)**, the SQL
script line where that flow is expressed. Selecting an edge in the L2 graph
highlights its script line in the SQL panel; the closure-level highlight set
is the union of the per-edge lines over the filtered edges.

**Edge = one data flow.** Every L2 edge represents exactly one data flow
between its endpoints. If multiple distinct flows exist between the same two
nodes, they are emitted as **multiple edges** — flows are never merged into
one edge. (Consequence: edge count == data-flow count. This matches the
benchmark's per-endpoint-pair coverage model in §7.2 — each of the 19
canonical pairs is one flow.)

**The highlight of an edge is exactly ONE script line** — never a range
(v3.3.147 refinement, user: "we only highlight a line instead of a range").
The line is the flow's **anchor line** per §8.3. The range-expansion layer
(`sql_range_finder`) is removed — see §8.6.

### 8.2 What is NOT part of the feature

**There is no field highlight.** Highlighting script lines solely because a
field variable occurs there (the old `highlights` = lines of the closure's
field-like vars, e.g. `[[18,18],[43,43],[158,158],[160,160]]`) is not wanted.
The field-occurrence display layer must be removed from the L2 response /
SQL panel. Field lines survive only as *fallback candidates* for edge spans
(§8.3.2) — they are not a display layer by themselves.

### 8.3 Edge-highlight contract (per edge e — anchor rules, in priority order)

1. **Field flow** (the field's value/occurrence moves between real lines):
   anchor = the field's **appearance line** — the var-carried `line_start`
   of the flow's source, I1 token-run semantics, extraction time.
   Canonical sample: L18, L43, L158, L160, L211, L213.
2. **READ flow** (a table's field is read — from the table's perspective,
   the queried field is inside the table by default): anchor = the
   **alias-definition / FROM line** of the alias the read happens through,
   NOT the field-use line (user ruling 2026-08-10). Canonical: L29, L84,
   L223, L199.
3. **Write group** (a field flows from a table to a write target): **one
   edge per field appearance**, each anchoring at its own appearance line —
   the write line, the value line, the read line — so every appearance is
   traceable (user ruling: 3 edges). Canonical stmt2: write L211, value
   L213, read L223.
4. **Synthetic-source flow** (source node is a VT `⟐ …@0` — no script
   presence of its own): anchor = the VT's **creation line**, taken at
   extraction time — statement-level VTs: the statement's **DML-clause
   line** (INSERT/MERGE keyword), NOT the whole-statement first-token anchor
   (TOP0's raw anchor is L9 `WITH …` while the flow lives at L160
   `INSERT OVERWRITE …` — probe-verified); subquery VTs: their own SELECT
   line (`⟐ subq` → L26, `⟐ subq1` → L22). VT-TARGETED edges never use the
   creation line — they keep the feeding var's exact line (e.g.
   `p1@29 → ⟐subq@0` anchors at L29, the subquery's FROM). Using the
   creation line there would collapse hub edges (`rollover@9 → ⟐output`,
   `loan_final@64 → ⟐output`, `⟐output → sup@160` → all L160) and lose
   per-flow granularity (§8.1) — a creation line never overrides an
   available exact line.
5. **Chain flow** (TABLE_FLOW/ALIAS/DML pass-through): anchor = the flow's
   entry line — the source node's def line.
6. **SCHEMA flow** (structure — container → member: "the field belongs to
   the table/VT", ruled in 2026-08-10): anchor = the **member node's
   appearance line** (the field's var-carried `line_start`; a VT member
   anchors at its creation line). Canonical: `p1@29 → p1.data_dt@43` → 43,
   `p1@84 → p1.data_dt@158` → 158 (sup seed), `p2@199 → p2.data_dt@202` → 202 —
   all lines already anchored by the member field's flow edges (pairs
   3/7/E4); shared lines with multiplicity, accepted.
7. **SUBSET flow** (bridge — column-set membership: "this statement's
   column set is part of the target's columns", ruled in 2026-08-10):
   anchor = the **source node's def line**. Canonical: `sup@223 →
   rrcdm@211` → 223 (already pair 18's anchor post-fix). The seven
   promoted pairs stop being SUBSET at extraction (rule 1/5 anchors
   apply); only the residual bridge takes rule 7.

**Guarantee:** every edge's highlight = exactly **one script line ≥ 1**.
Line 0 or a missing line is a defect, never a valid highlight. **Every
edge in the L2 graph carries a highlight** (user ruling 2026-08-10: "there
is an edge, there should be a highlight").

**The canonical 19-pair spec** (this sample — 16 canonical pairs + 3 flows;
supersedes the 16-pair §7.2 highlight framing):

| # | Pair | Kind | Anchor |
|---|------|------|--------|
| 1 | `data_dt@18 → bdm_acc_loan_info@16` | field flow | 18 |
| 2 | `bdm_acc_loan_info@16 → rollover_loan_info@9` | chain | 16 |
| 3 | `p1.data_dt@43 → ⟐ subq@0` | field flow | 43 |
| 4 | `bdm_acc_loan_info@29 → ⟐ subq@0` | chain | 29 |
| 5 | `⟐ subq@0 → ⟐ subq1@0` | chain (VT→VT) | 26 (creation) |
| 6 | `⟐ subq1@0 → rollover_loan_info@9` | chain | 22 (creation) |
| 7 | `p1.data_dt@158 → loan_final@64` | field flow | 158 |
| 8 | `bdm_acc_loan_info@84 → loan_final@64` | chain | 84 |
| 9 | `rollover_loan_info@9 → loan_final@64` | chain (ALIAS) | 9 |
| 10 | `loan_final@64 → bdm_acc_loan_info_sup@160` | chain (ALIAS) | 64 |
| 11 | `bdm_acc_loan_info_sup@160 → bdm_acc_loan_info_sup@160` | chain (self-join) | 160 |
| 12 | `data_dt@160 → bdm_acc_loan_info_sup@160` | field flow | 160 |
| 13 | `p1.data_dt@43 → bdm_acc_loan_info@29` | READ | 29 (alias-def) |
| 14 | `p1.data_dt@158 → bdm_acc_loan_info@84` | READ | 84 (alias-def) |
| 15 | `⟐ output@0 → bdm_acc_loan_info_sup@160` | synthetic | 160 (creation) |
| 16 | `bdm_acc_loan_info_sup@160 → rrcdm_job_log_exec_par@211` | write | 211 |
| 17 | `data_dt@213 → rrcdm_job_log_exec_par@211` | value (write group) | 213 |
| 18 | `data_dt@225 → bdm_acc_loan_info_sup@223` | READ (write group) | 223 (alias-def) |
| 19 | `p2.data_dt@202 → p2@199` | READ (self-join key) | 199 (alias-def) |

**Self-join reads are data flows** (user ruling 2026-08-10): the script
joins the table to itself (`LEFT JOIN bdm_acc_loan_info_sup p2 …
AND p2.data_dt = DATEADD(DATE'$(load_date)',-1,'DD')`); the join-key read at
L202 is a genuine data flow and belongs in the spec — pair 19.

**The boundary rule — what counts as a flow (Flaw-5, ruled 2026-08-10).**
An edge counts as a flow iff:
1. its anchor line is one of the three real anchor kinds (field appearance /
   alias-definition/FROM / VT-creation) — this covers every value-carrying
   edge (REF, AGGREGATE, TRANSFORM, WINDOW, COMPUTED, FILTER, JOIN,
   CORRELATED, SET_OP) and every read; OR
2. it is a walkable chain edge (TABLE_FLOW / ALIAS / DML) — the row-set
   carrier between field appearances; anchor = the flow's entry line (the
   source table's def line, or the VT's creation line). **Chain edges
   count** (user ruling, 2026-08-10: "I think this is better: chain edges
   count") — the trace stays continuous between field appearances (e.g.
   L18 → sup at L160 via rollover_loan_info@9 / loan_final@64); the field
   is *inside* the flow, not printed on the carrier's lines (a chain
   anchor may carry no field token — that is what makes the chain clause a
   separate kind).
Highlighted — **every edge in the L2 graph** (supersedes the peremptory
exclusions below; user ruling 2026-08-10: "There is an edge, there should
be a highlight… every edge in L2 representing a data flow, doesn't it? so
the scheme edge is also included"):
- **SCHEMA containment edges count** (structure kind — "belongs to") —
  anchor rule 6 (member's appearance line).
- **SUBSET/BRIDGE edges count** (bridge kind — column-set membership) —
  anchor rule 7 (source's def line). The seven promoted pairs stop being
  SUBSET at extraction anyway; on this sample only ONE residual bridge
  remains (`sup@223 → rrcdm@211`, sup seed).
- **INDIRECT** counts iff the field's token sits at an endpoint.
Former exclusions (kept as history; superseded by the ruling above):
- ~~SUBSET/BRIDGE never counts~~ — the `data_dt@213 → rrcdm@211` bridge
  variant is pair 17 (promoted to value-write), the `sup@223 → rrcdm@211`
  bridge is now highlighted as B1 (anchor 223).
- ~~SCHEMA containment never counts~~ (I5 — structure, not a value flow) —
  now highlighted as S1–S5 (structure kind, rule 6).
Prerequisite (accepted with the rule; probe-pinned list, 2026-08-10): the
machinery must promote the mislabeled real flows out of SUBSET — the probe
shows **SEVEN** canonical pairs currently typed SUBSET (the earlier 17/19
list was incomplete):
- SUBSET/BRIDGE → honest type: pair 1 (`data_dt@18 --SUBSET/BRIDGE-->
  bdm_acc_loan_info@16` — the field's filter, promote to FILTER/REF-family),
  pair 2 (`bdm@16 --SUBSET/BRIDGE--> rollover@9` — the row-set carrier,
  promote to TABLE_FLOW), pair 12 (`data_dt@160 --SUBSET/BRIDGE-->
  sup@160` — the partition write, promote to value-write), pair 17
  (`data_dt@213 --SUBSET/BRIDGE--> rrcdm@211` — the value write, promote to
  value-write);
- SUBSET/READ → honest read: pair 13 (`p1.data_dt@43 --SUBSET/READ-->
  p1@29`), pair 14 (`p1.data_dt@158 --SUBSET/READ--> p1@84`), pair 19
  (`p2.data_dt@202 --SUBSET/READ--> p2@199` — read, REF/read
  semantics); pair 18 joined this list with the Defect-5 fix (W2): L225's
  `data_dt` registers and its read edge is emitted REF/read (no SUBSET
  escape — pair 18, anchor 223, §8.5).
Without the promotions, the peremptory exclusion would wrongly drop flows
already ruled in.

**Probe findings (2026-08-10) — how the graph realizes the 19 pairs:**
- Pairs 4 and 8 have **no single direct edge** — they are realized as two
  hops (`bdm@29 --ALIAS--> p1@29` + `p1@29 --TABLE_FLOW/FROM--> ⟐subq@0`;
  same shape at @84). Both hops anchor at the pair's line (29 / 84); the
  benchmark normalizes via `_canon_key` (alias node → canonical source
  table) and matches the pair through the FROM hop.
- Pairs 9 and 10 are **direct edges** — `p6@155` and `p1@198` never
  materialize as nodes (`TABLE_FLOW/REFERENCE` and `TABLE_FLOW/INSERT`).
- **Extras beyond the 19 — COUNTED (resolved 2026-08-10, option 1).** The
  closures also carry real flows with real anchors: the ALIAS hops
  `bdm@29→p1@29` (29), `bdm@84→p1@84` (84), `sup@160→p2@199` (160) and
  the JOIN condition `p2.data_dt@202 --JOIN/JOIN_CONDITION--> ⟐output@0`
  (202 — the condition line itself). They are genuine flows per the
  boundary rule (ALIAS chain / value-carrying with a field-appearance
  anchor) and NO new exclusion rule was added — they each carry
  `highlight_line` like any flow. They are **verified extras**: pinned in
  the benchmark (§8.5) with exact anchors so they cannot drift. Three
  anchors coincide with the 19 pairs' lines (29 / 84 / 160); the JOIN adds
  the new line **202** (the condition line — correct to highlight). The
  alternative (exclude them, payload = exactly 19) was offered and
  declined: it would need an exclusion rule contradicting "chain edges
  count", and clicking the JOIN edge would highlight nothing at L202.
- The SCHEMA containment edges (`p1@29→p1.data_dt@43`,
  `p1@84→p1.data_dt@43/158` — 43 bdm seed, 158 sup seed,
  `p2@199→p2.data_dt@202`) and the residual
  bridge (`sup@223→rrcdm@211`) are now **highlighted too** (ruling
  2026-08-10, every edge is a data flow unit) — pinned as S1–S5 and B1 in
  the benchmark (§8.5), anchors = rule 6/7 (43, 202, 223 — all
  already-lit lines).

**Scope note — robustness, NOT the contract.** Every canonical edge must
have its exact anchor line per the rules above; a canonical edge without one
is a solution defect (bug to fix), never a "hard case". Edge 18's anchor
(223) depended on L225 being extracted — the Defect-5 gap, resolved by the
token-run extension (bug list §v3.3.147 addendum 2, W2 landed 2026-08-10):
the var exists and the edge is live (probe-verified).

### 8.4 Counting invariant

- Per edge: exactly **one primary line** ⇒ per-edge highlight count == edge
  count. **Every edge in the L2 graph highlights** (ruling 2026-08-10) —
  there is no excluded category. Canonical contract on this sample: **19
  canonical pairs + 4 verified extras + 6 SCHEMA/residual-bridge entries
  (S1–S5, B1) + 4 chain-completeness entries (C1–C4) = 33 highlight
  entries → 16 distinct lines** (L160 = 5 entries [pairs 11/12/15 + E3],
  L29 = 3 [pairs 4/13 + E1], L84 = 3 [pairs 8/14 + E2]; S/B/C anchors at
  43/202/223/9/64/199 — all already covered). Every closure edge is
  pinned (§8.5) so the payload count is deterministic, not open-ended.
- Multiple edges may share one line — shared anchors are accepted (L160:
  pairs 11/12/15 + E3; L29: pairs 4/13 + E1; L84: pairs 8/14 + E2; L43's
  FILTER and READ flows now anchor apart — 43 and 29 — per the READ rule).
  Deduping shared lines for display is a *rendering* decision, never a
  semantic one; the edge→line mapping is one-to-one and the benchmark
  asserts it **per edge**.
- The write group (pairs 16/17/18) keeps every appearance traceable: the
  write line 211, the value line 213, the read line 223 — three edges, one
  per appearance, per the user's 3-edge ruling.

### 8.5 Highlight ground truth for testing (CANONICAL_EDGE_LINES — complete)

`CANONICAL_HIGHLIGHTS` (field lines), `CANONICAL_PROPAGATED`, and the
earlier `CANONICAL_EDGE_RANGES` plan are all superseded. The test ground
truth is **CANONICAL_EDGE_LINES**: the 19 canonical pairs + 4 verified
extras + 6 SCHEMA/residual-bridge entries + 4 chain-completeness entries
(§8.3), each with its exact anchor line and closure seed. **Every edge of
each closure is listed — the table is the closure bijection (nodes/edges/
highlights), not a subset** (C1–C4 complete the bdm 22 edges and sup 12
edges; probe-pinned 2026-08-10).

**The complete table — 33 entries, this sample, post-promotion state:**

| # | Pair | Kind | Real type (post-promotion) | Seed | Anchor |
|---|------|------|---------------------------|------|--------|
| 1 | `data_dt@18 → bdm@16` | field flow | FILTER/REF (promoted) | bdm | 18 |
| 2 | `bdm@16 → rollover@9` | chain | TABLE_FLOW (promoted) | bdm | 16 |
| 3 | `p1.data_dt@43 → ⟐subq` | field flow | FILTER/CONDITION | bdm | 43 |
| 4 | `bdm@29 → ⟐subq` | chain | TABLE_FLOW/FROM (2-hop: +ALIAS) | bdm | 29 |
| 5 | `⟐subq → ⟐subq1` | chain | TABLE_FLOW/SUBSELECT | bdm | 26 |
| 6 | `⟐subq1 → rollover@9` | chain | TABLE_FLOW/SUBSELECT | bdm | 22 |
| 7 | `p1.data_dt@158 → loan_final` | field flow | FILTER/CONDITION | bdm | 158 |
| 8 | `bdm@84 → loan_final` | chain | TABLE_FLOW/FROM (2-hop: +ALIAS) | bdm | 84 |
| 9 | `rollover@9 → loan_final` | chain | TABLE_FLOW/REFERENCE | bdm | 9 |
| 10 | `loan_final@64 → sup@160` | chain | TABLE_FLOW/INSERT | bdm | 64 |
| 11 | `sup@160 → sup@160` | chain | TABLE_FLOW/SELF_JOIN | bdm+sup | 160 |
| 12 | `data_dt@160 → sup@160` | field flow | value-write (promoted) | bdm+sup | 160 |
| 13 | `p1.data_dt@43 → bdm@29` | READ | read (promoted) | bdm | 29 |
| 14 | `p1.data_dt@158 → bdm@84` | READ | read (promoted) | bdm | 84 |
| 15 | `⟐output@0 → sup@160` | synthetic | TABLE_FLOW/INSERT | bdm+sup | 160 |
| 16 | `sup@160 → rrcdm@211` | write | TABLE_FLOW/WRITE_READ (DML-routed) | bdm+sup | 211 |
| 17 | `data_dt@213 → rrcdm@211` | value | value-write (promoted) | sup | 213 |
| 18 | `data_dt@225 → sup@223` | READ | read (post-fix, promoted) | sup | 223 |
| 19 | `p2.data_dt@202 → p2@199` | READ | read (REF, promoted) | sup | 199 |
| E1 | `bdm@29 → p1@29` | ALIAS hop | ALIAS | bdm | 29 |
| E2 | `bdm@84 → p1@84` | ALIAS hop | ALIAS | bdm | 84 |
| E3 | `sup@160 → p2@199` | ALIAS hop | ALIAS | sup | 160 |
| E4 | `p2.data_dt@202 → ⟐output@0` | JOIN cond | JOIN/JOIN_CONDITION | sup | 202 |
| S1 | `p1@29 → p1.data_dt@43` | structure | SCHEMA/TABLE_COLUMN | bdm | 43 |
| S2 | `p1@29 → p1.data_dt@43` | structure | SCHEMA/TABLE_COLUMN | bdm | 43 |
| S3 | `p1@84 → p1.data_dt@43` | structure | SCHEMA/TABLE_COLUMN | bdm | 43 |
| S4 | `p1@84 → p1.data_dt@43` | structure | SCHEMA/TABLE_COLUMN | bdm | 43 |
| S5 | `p2@199 → p2.data_dt@202` | structure | SCHEMA/TABLE_COLUMN | sup | 202 |
| B1 | `sup@223 → rrcdm@211` | bridge | SUBSET (residual) | sup | 223 |
| C1 | `rollover@9 → ⟐output@0` | chain | TABLE_FLOW/REFERENCE | bdm | 9 |
| C2 | `loan_final@64 → ⟐output@0` | chain | TABLE_FLOW/REFERENCE | bdm | 64 |
| C3 | `p2@199 → ⟐output@0` | chain | TABLE_FLOW/FROM | sup | 199 |
| C4 | `p2@199 → sup@160` | chain | TABLE_FLOW/INSERT | sup | 199 |

Real-type column = the state AFTER the §8.3 promotions land; today's
probe shows the promotions are live (rows 1/2/12/13/14/17/19 emitted as
FILTER/TABLE_FLOW/REF/…, §8.3) and row 18 = REF/read (W2 — Defect-5
fixed; FILTER companion anchored 225). Pair names use canonical endpoints;
pairs 4/8 and E1–E3 are
matched with `_canon_key` alias normalization. S1–S5/B1 (probe-pinned
2026-08-10): the SCHEMA containment edges and the single residual SUBSET
bridge in the two closures — every edge in the L2 graph highlights
(ruling 2026-08-10); S3/S4 confirm both p1 alias instances sync to the
shared `p1.data_dt` field node (hl=43 in the bdm seed — the 158 instance
survives only in the sup seed) (Sync 1). C1–C4: the closure's
remaining chain edges into `⟐output@0` / from p2 (chain kind, rule 5 —
source def line). Per-seed completeness (probe): bdm = pairs 1–16 +
E1/E2 + S1–S4 + C1/C2 = **24 entries / 22 closure edges** (S2/S4 collapse
into S1/S3 — one SCHEMA edge per p1 alias, asserted twice); sup = pairs
11, 12, 15, 16, 17, 18(post-fix), 19 + E3/E4 + S5 + B1 + C3/C4 = **13
entries = 13 closure edges (pair 18 live since W2, 2026-08-10)**.

Probe finding (2026-08-10): in the bdm seed the L43 and L158 `p1.data_dt`
instances both resolve to the physical `bdm_acc_loan_info` node and merge
into ONE field node (dedup key (parent_table_id, undecorated_label,
stmt_idx) — both are stmt-0 CTE-zone instances, by design), so S2/S4
collapse into S1/S3 (one SCHEMA edge per p1 alias, hl=43) while the sup
seed keeps distinct instances and its hl=158 SCHEMA edges (p1@84→158,
p1@198→158).

**Assertion spec — `test_edge_lines`** (per entry, on its seed):
(a) the edge EXISTS in the closure (canonical normalization);
(b) its `highlight_line` == the expected anchor — **exact match required**;
    a fallback line FAILS the test as a solution defect;
(c) line ≥ 1 (line 0 is a defect).
Canonical pairs (1–19): existence + exact anchor. Verified extras
(E1–E4) and the SCHEMA/bridge entries (S1–S5, B1): existence + exact
anchor (pinned so the payload count is deterministic). Pair 18 is
asserted present (W2 landed 2026-08-10): REF/read with the exact anchor
223 (the FILTER companion at 225 is pinned as an extra); the test's
PAIR18_KNOWN_GAP constant is flipped and the KNOWN-GAP branch removed.

**Closure seeds (probe-pinned 2026-08-10): no single L2 search seed
covers all 19 pairs.** The `bdm_acc_loan_info.data_dt` seed yields pairs
1–16 + E1/E2 + S1–S4 + C1/C2 (16 nodes / 22 edges); the
`bdm_acc_loan_info_sup.data_dt` seed yields pairs 11, 12, 15, 16, 17, 19
+ E3/E4 + S5 + B1 + C3/C4 (9 nodes / 13 edges; pair 18 live since W2 —
the W2 read-edge expansion and VT creation lines grew the actual closures
far beyond these canonical counts; the closure-bijection model is under
review, see the benchmark-model note in the integration report). The
33-entry spec is the UNION over the two seeds; the Seed column states
where each entry is asserted. The §7.2 closure spec (13 nodes / 16 edge
pairs / 2 sinks) is UNCHANGED — only the highlight layer is redefined.

### 8.6 Current-system gaps this definition exposes (bug list §v3.3.147)

1. The field-highlight layer still exists (level2 `highlights` from field
   vars + `highlight_strategies` `single_line`) — must be removed together
   with the `propagated` payload field. After removal the L2 payload carries
   per-edge `highlight_line` only (plus the per-edge `flow_kind`/`reason`
   of §8.8) — no line-list payload fields remain.
2. `sql_range_finder` is removed entirely (line-only model, §8.1). The L2
   payload replaces edge `sql_range`/`sql_ranges` with edge `highlight_line`;
   the frontend click highlight uses that one line. The range behaviors die
   with the module — including the Bug-4 AND/OR continuation extension
   (v3.3.66): a multi-line WHERE lights only the anchor line now.
   **CONFIRMED by the user (2026-08-10): "one line highlight is very simple
   and efficient. Just use it."** — accepted, not a regression to repair.
3. Line-resolution collapse 3→1 + no stale-cache repair (recorded rulings,
   bug list §v3.3.147 addendum 2) — the Defect-5 fix and the duplicate
   `data_dt@213` split landed here (W2, 2026-08-10).
4. Type promotions at extraction time — **three** pairs, all probe-pinned
   2026-08-10: pair 12 (`data_dt@160 --SUBSET/BRIDGE--> bdm_acc_loan_info_sup@160`
   — the partition write must promote to field-flow/value-write), pair 17
   (SUBSET/BRIDGE → value-write), pair 19 (SUBSET/READ → read, REF);
   VTs carry creation lines (pairs 5/6/15). Without the promotions, the
   Flaw-5 boundary rule (ruled 2026-08-10) would wrongly exclude flows
   already ruled in.
5. Benchmark rework to the 19-pair `CANONICAL_EDGE_LINES` (§8.5).

### 8.7 Real edge types → flow kind → highlight contract (16-row mapping, 2026-08-10)

> User requirement: the definition includes **both edge types** (the real
> 16-type taxonomy and the semantic flow kind) **and whether the edge
> highlights**, with the detailed rules. Kind is assigned **per edge** (real
> type + endpoint roles), never per type alone — a REF edge pointing back at
> its owning table is a READ (rule 2), the same type flowing forward is a
> field flow (rule 1). The kind and the anchor line are both derived at
> extraction time (never reconstructed at render).

| # | Real type | Flow kind | Highlighted | Anchor rule | Canonical instances / notes (probe 2026-08-10) |
|---|-----------|-----------|-------------|-------------|------------------------------------------------|
| 1 | TABLE_FLOW | chain | ✅ | 5 — entry line (source def) or VT creation | pairs 2 (post-promotion), 4 & 8 (FROM hop), 5 & 6 (SUBSELECT), 9 (REFERENCE), 10 (INSERT), 11 (SELF_JOIN), 15 (INSERT) |
| 2 | ALIAS | chain | ✅ | 5 — entry line | hops `bdm@29→p1@29`, `bdm@84→p1@84`, `sup@160→p2@199` (extras, §8.10) |
| 3 | DML | write | ✅ | 3 — write line | pair 16 (WRITE_READ @211 — payload TABLE_FLOW, DML-routed) |
| 4 | REF | field flow / READ | ✅ | 1 — appearance; 2 — alias-def (READ variant) | promotion target for pairs 13/14; pair 18 (W2, 2026-08-10 — read variant, anchor 223) |
| 5 | AGGREGATE | field flow | ✅ | 1 | no instance in the canonical sample |
| 6 | TRANSFORM | field flow | ✅ | 1 | no instance in the canonical sample |
| 7 | WINDOW | field flow | ✅ | 1 | verification sample: `snowflake_qualify.sql` (2 edges, e.g. `order_date@4 --WINDOW--> rn@6` → anchor 4) |
| 8 | COMPUTED | field flow | ✅ | 1 | no instance in the canonical sample |
| 9 | FILTER | field flow | ✅ | 1 | pairs 3, 7 (CONDITION); pair 1 post-promotion |
| 10 | JOIN | field flow | ✅ | 1 — appearance | pair 19 post-promotion (read, REF); extra `p2.data_dt@202 --JOIN/JOIN_CONDITION--> ⟐output@0` (anchor 202) |
| 11 | CORRELATED | — (config-only) | — | — | **never emitted as a `relationship`** — correlated subqueries are emitted as INDIRECT with operation `CORRELATED`/`CORRELATED_OUT` (probe, dependency_graph.py:487/495); style/range config only |
| 12 | SET_OP | field flow | ✅ | 1/4 — **15** (probe-pinned) | verification sample: `tpcds_qualified/86.sql` (`union_result@0 --SET_OP--> results_rollup@14` → anchor 15: rule 4 creation line — the set-op body's first token at L15, NOT the CTE header L14) |
| 13 | SUBQUERY | field flow / chain | ✅ | 1 / 5 | not observed on the canonical sample; VT chains there are TABLE_FLOW/SUBSELECT |
| 14 | INDIRECT | filter (correlated) | ✅ iff the field's token sits at an endpoint | endpoint-decided | verification sample: `spider_complex/046_pets_1_s6.sql` (15 edges, e.g. `T1.stuid@3 --INDIRECT/CORRELATED--> T1.stuid@3` → anchor 3) |
| 15 | SCHEMA | structure | ✅ (ruled 2026-08-10) | 6 — member's appearance line | `p1@29→p1.data_dt@43`, `p1@84→p1.data_dt@43/158` (43 bdm seed, 158 sup seed), `p2@199→p2.data_dt@202` (S1–S5) |
| 16 | SUBSET | bridge | ✅ (ruled 2026-08-10) — the seven promoted pairs (1, 2, 12, 13, 14, 17, 19) stop being SUBSET at extraction; the residual bridge takes rule 7 | 7 — source's def line | residual `sup@223→rrcdm@211` (B1); `data_dt@213→rrcdm@211` is pair 17 (promoted) |

Per-pair real-type map (probe-pinned; the 19 pairs as they exist today):

| # | Pair | Current real type | Action |
|---|------|-------------------|--------|
| 1 | `data_dt@18 → bdm@16` | SUBSET/BRIDGE | promote → FILTER/REF-family |
| 2 | `bdm@16 → rollover@9` | SUBSET/BRIDGE | promote → TABLE_FLOW |
| 3 | `p1.data_dt@43 → ⟐subq` | FILTER/CONDITION | none |
| 4 | `bdm@29 → ⟐subq` | 2-hop: ALIAS + TABLE_FLOW/FROM | none (pair matched via FROM hop) |
| 5 | `⟐subq → ⟐subq1` | TABLE_FLOW/SUBSELECT | none |
| 6 | `⟐subq1 → rollover@9` | TABLE_FLOW/SUBSELECT | none |
| 7 | `p1.data_dt@158 → loan_final` | FILTER/CONDITION | none |
| 8 | `bdm@84 → loan_final` | 2-hop: ALIAS + TABLE_FLOW/FROM | none |
| 9 | `rollover@9 → loan_final` | TABLE_FLOW/REFERENCE | none (p6@155 not a node) |
| 10 | `loan_final@64 → sup@160` | TABLE_FLOW/INSERT | none (p1@198 not a node) |
| 11 | `sup@160 → sup@160` | TABLE_FLOW/SELF_JOIN | none |
| 12 | `data_dt@160 → sup@160` | SUBSET/BRIDGE | promote → value-write |
| 13 | `p1.data_dt@43 → bdm@29` | SUBSET/READ | promote → read (REF) |
| 14 | `p1.data_dt@158 → bdm@84` | SUBSET/READ | promote → read (REF) |
| 15 | `⟐output@0 → sup@160` | TABLE_FLOW/INSERT | none |
| 16 | `sup@160 → rrcdm@211` | TABLE_FLOW/WRITE_READ (DML-routed) | none |
| 17 | `data_dt@213 → rrcdm@211` | SUBSET/BRIDGE | promote → value-write |
| 18 | `data_dt@225 → sup@223` | REF (read, W2) | promoted → read (anchor 223; FILTER companion at 225) |
| 19 | `p2.data_dt@202 → p2@199` | SUBSET/READ | promote → read (REF) |

### 8.8 L2 display of flow kind — design RULED (2026-08-10, user)

**User ruling (2026-08-10):** "Please label flow-kind to the edges in L2
ignoring edge type, sql, and so on. When clicking the sql is highlighted,
and the reason should be explained below the sql panel (maybe we need a
new panel). Also the reason should include the string format data flow."

**The display contract (R25, ruled):**
1. **Edge labels — flow kind only, always visible.** Every L2 edge displays
   its flow-kind label at the edge midpoint. The label carries the flow
   kind ONLY — never the edge type, never SQL text. Kind names are the
   §8.7 canonical set: `chain`, `field flow`, `read`, `write`, `filter`,
   `structure`, `bridge` — **every edge is highlighted** (ruled
   2026-08-10: "there is an edge, there should be a highlight"; the
   SCHEMA edge is a data flow unit too), so every label renders in the
   edge's category color. No toggle — labels always on.
2. **Click → SQL highlight + reason panel.** Clicking an edge (a) scrolls
   the SQL panel to `highlight_line` and highlights exactly that one line
   (existing single-line behavior; AND/OR continuation lights only the
   anchor — CONFIRMED 2026-08-10), and (b) shows the reason in a NEW panel
   below the SQL panel: flow kind + anchor line + the reason string.
3. **Reason string = full path + current edge location (ruled 2026-08-10).**
   Format: `<flow kind> — <flow string>`. The reason panel shows BOTH:
   - **Full path (overview)** — the walkable chain from the closure entry
     (the searched seed's field) to this edge's target, rendered as
     `{label}@L{line}` joined by ` → ` (e.g. pair 4, bdm seed: `chain —
     bdm_acc_loan_info.data_dt@L18 → bdm.data_dt@L16 → p1.data_dt@L29 →
     ⟐subq@L0`).
   - **Current edge location (orientation)** — the clicked edge's own
     segment (`source@L{line} → target@L{line}`) is emphasized within the
     path (bold, edge category color) so the user sees exactly where the
     clicked edge sits in the flow.
   The flow string is built at L2 build time from the closure walk
   (extraction-time info — never reconstructed at render; never-patch
   rule). Per-pair strings are pinned during the W1 probe round /
   benchmark verification. The anchor (rule 5 chain entry) may differ
   from the string's start — the panel shows `anchor: L{line}`
   separately.
4. **Secondary surfaces (unchanged):** hover tooltip keeps edge type + kind
   + anchor + reason; the legend groups the 16 types by flow kind with
   ✅/❌ marks.

Open micro-decisions — flow-string scope: **RESOLVED (both, item 3)**.
Excluded-edge labels: **RESOLVED (2026-08-10)** — the user ruled every
edge in L2 is a data flow unit and highlights, SCHEMA included; there is
no excluded category anymore (S1–S5, B1 pinned in §8.5).

### 8.9 Verification plan — the four types absent from the canonical sample (user ruling: verify-first)

The user chose (b) verify-first: find real-SQL samples for INDIRECT /
WINDOW / CORRELATED / SET_OP and verify their anchors **before** any
implementation. Corpus scan (2026-08-10, 256 files + full tpcds_qualified):

| Type | Candidate script | Lines | Evidence | Expected anchor |
|------|------------------|-------|----------|-----------------|
| WINDOW | `dialect_test/snowflake_qualify.sql` | 9 | 2 WINDOW edges (`order_date@4 --WINDOW--> rn@6`, `customer_id@3 --WINDOW--> rn@6`) | rule 1 — source field's appearance line (**4 / 3 — probe-CONFIRMED**) |
| SET_OP | `tpcds_qualified/86.sql` | 32 | 1 SET_OP (`union_result@0 --SET_OP--> results_rollup@14`) + 4 WINDOW in the same script | rule 4 — synthetic-source creation line: **15 (probe-pinned)** — the set-op body's first token at L15; L14 is the `results_rollup` CTE header (the target's line — no anchor rule is target-based for value-carrying edges) |
| INDIRECT | `spider_complex/046_pets_1_s6.sql` | 3 | 15 INDIRECT (`T1.stuid@3 --INDIRECT/CORRELATED--> T1.stuid@3`, 5 CORRELATED + 10 CORRELATED_OUT) | endpoint-decided — token at both endpoints → anchor **3 (probe-CONFIRMED, all 15 edges)** |
| CORRELATED | **no script produces a `CORRELATED` relationship** | — | emitted as INDIRECT/CORRELATED (dependency_graph.py:487/495) | n/a — the taxonomy row is config-only; INDIRECT's rule covers correlated subqueries |

Probe round (DONE 2026-08-10, work list W1): anchors pinned on all three
scripts — WINDOW 4/3 ✓, INDIRECT 3 (all 15 edges) ✓, SET_OP **15**
(corrected: the rule-4 creation line of the synthetic `union_result` VT is
the set-op body's first token at L15, not the CTE header L14). Benchmark
rows for the three samples (`test_verification_samples.py`):

| Sample | Edge | rel/op | Anchor | Surfaces in closure(s) of |
|--------|------|--------|--------|---------------------------|
| snowflake_qualify.sql | `order_date@4 → rn@6` | WINDOW/REFERENCE | 4 | `orders/order_date`, `orders/customer_id`, `⟐ output/rn` |
| snowflake_qualify.sql | `customer_id@3 → rn@6` | WINDOW/REFERENCE | 3 | same 3 seeds |
| 86.sql | `total_sum@15 → rank_within_parent@25` | WINDOW/REFERENCE | 15 | `results_rollup/{total_sum,g_class,i_category,lochierarchy}`, `⟐ output/rank_within_parent`, `⟐ union1/total_sum` |
| 86.sql | `g_class@15 → rank_within_parent@25` | WINDOW/REFERENCE | 15 | same 6 seeds |
| 86.sql | `i_category@15 → rank_within_parent@25` | WINDOW/REFERENCE | 15 | same 6 seeds |
| 86.sql | `lochierarchy@15 → rank_within_parent@25` | WINDOW/REFERENCE | 15 | same 6 seeds |
| 86.sql | `union_result@0 → results_rollup@14` | SET_OP/SET | 15 | **none — full-graph only** |
| 046_pets_1_s6.sql | `T1.stuid@3 → T1.stuid@3` | INDIRECT/CORRELATED | 3 | `student/stuid` |
| 046_pets_1_s6.sql | `T2.stuid@3 → T2.stuid@3` | INDIRECT/CORRELATED | 3 | `has_pet/stuid` |
| 046_pets_1_s6.sql | `T2.petid@3 → T2.petid@3` | INDIRECT/CORRELATED | 3 | `has_pet/petid` |
| 046_pets_1_s6.sql | `T3.petid@3 → T3.petid@3` | INDIRECT/CORRELATED | 3 | `pets/petid` |
| 046_pets_1_s6.sql | `T3.pettype@3 → T3.pettype@3` | INDIRECT/CORRELATED | 3 | `pets/pettype` |
| 046_pets_1_s6.sql | 10 CORRELATED_OUT edges (subquery columns → `T1.fname@3`/`T1.age@3`) | INDIRECT/CORRELATED_OUT | 3 | **none — full-graph only** |

The SET_OP and CORRELATED_OUT rows cannot be asserted through seeded L2
closures (their VTs are reachable only via SET_OP/SUBSET bridges, which
the field closure walk never crosses) — they are asserted on the
unfiltered graph. CORRELATED confirmed never emitted as a `relationship`
(always INDIRECT with operations `CORRELATED`/`CORRELATED_OUT`,
dependency_graph.py:487/495).

### 8.10 Open confirmations (2026-08-10) — everything else is ruled

1. **L2 display design — RULED (2026-08-10)** (§8.8): flow-kind labels on
   the edges (kind only, always visible, category color — **every edge
   highlights**, SCHEMA/SUBSET included, no excluded category); click →
   SQL anchor highlight + NEW reason panel below the SQL panel; reason
   includes the string-format data flow — full path + current edge
   location (both, ruled). All open micro-decisions resolved; the only
   remaining gate is G2 (work list approval).
2. **Extras counting — RESOLVED (2026-08-10): counted per the boundary
   rule** (option 1); the 4 verified extras (E1–E4) are pinned in the
   benchmark (§8.5) with exact anchors. The exclusion alternative
   (payload = exactly 19) was declined: it needs a new exclusion rule
   contradicting "chain edges count" and would kill the L202 click.
3. **Two-seed benchmark (§8.5) — recorded as the test design**:
   `test_edge_lines` asserts per the Seed column (pairs 1–16 + E1/E2 on
   the bdm seed; 17/19 + E3/E4 + 18 post-fix on the sup seed). The L2
   search seed determines which zone renders — current behavior, confirmed
   by probe.
