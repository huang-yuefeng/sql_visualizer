# Benchmark Case Build Method

> The step-by-step method for building one Jaccard benchmark case. This is the
> canonical procedure — every new case (seed) is produced by following it from
> top to bottom, never by copying the engine's own output into the ground truth.
> Companion docs: the per-case `tools/GROUND_TRUTH_*.md` specs, the harness
> `backend/tests/test_jaccard_benchmark.py`, and the fixture
> `backend/tests/jaccard_canonical.py`.

## The two ground-truth rules (non-negotiable)

1. **Independence** — the canonical closure (`B`) is derived by READING THE SQL,
   never from the engine's emitted form. The engine's output (`A`) is only used to
   *probe* the served shape so the canonical rows can be pinned precisely; it is
   never the source of a canonical entry.
2. **Set equality, not size** — `A = B` iff recall = precision = 1.0, i.e.
   `|A∩B|/|B| == 1` **and** `|A∩B|/|A| == 1`. A size match with disjoint sets
   (`|A|=|B|`, recall = precision = 0) is a FAIL, never a pass. There is no "close
   enough" floor — every canonical entry must be present and nothing extra may leak.

## Step 0 — choose the case

A case is the triple `(script, physical_table, field)`. Pick the physical table and
field first (the search pair), then the script that exercises it.

- The pair must be a **physical** table/field (a real column — schema-declared,
  script-referenced, or an INSERT/CTAS/UPDATE/MERGE output alias). Computed/derived
  aliases are not searchable and must not seed a case.
- For coverage cases, choose `(table, field)` from the same sample folder by
  *random* (arbitrary, not curated for a bug) so the benchmark broadens beyond the
  bug-driven cases.

## Step 1 — derive the canonical closure from SQL (independent)

Read the script and hand-write the three features of the canonical closure. Do this
BEFORE touching the running engine.

1. **Nodes** — the field's occurrences (`data_dt@18`), the tables/aliases/CTEs they
   pass through (`bdm_acc_loan_info@16`, `p1@29`, `rollover_loan_info@9`), the
   statement/derived virtual tables (`⟐ output@160`), and the sinks. Each entry is
   `label@line` (label + anchor line).
2. **Edges** — the endpoint pairs with their anchor line and semantic kind
   (`data_dt@18 → bdm_acc_loan_info@16`, field flow @18; `bdm_acc_loan_info@16 →
   rollover_loan_info@9`, chain @16; …). Alias nodes normalize to their canonical
   source table (`p1@29 ≡ bdm_acc_loan_info@29`).
3. **Highlights** — one anchor line per edge (the per-edge `highlight_line`).

Record the closure seeds too: one L2 search seed rarely covers every canonical
entry; note which seed asserts which rows.

## Step 2 — probe the served form

Index the script in a **disposable** workspace and run the real L2 search, then read
back the served graph. (Never the production `gps-sql` workspace — `cleanWorkspaces`
deletes real workspaces; use the throwaway container/workspace per the Playwright
memory.)

```bash
docker exec gps-sql-backend python3 -m pytest tests/ -q        # sanity before probing
# create + index + search a scratch workspace; read /workspace/{ws_id}/views/{view_id}/level2?script=&filter=
```

Pin the served edge ids / node ids / anchor lines only so the canonical rows can be
*matched* against the response (`jaccard_canonical.py` normalization).

## Step 3 — compare and classify every diff

For each difference between the hand truth and the served form, classify exactly one:

- **(a) solution defect** → the engine is wrong; file a bug in
  `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md`. Never patch the ground truth to match the
  engine, and never build a patch solution (extraction-time info only).
- **(b) ground-truth wrong** → the hand analysis was wrong; repair **the doc** with
  the evidence (which trial proved it, why the old entry was wrong). Never change the
  engine to match a wrong doc.
- **(c) known gap** → a real flow the engine does not yet emit; keep the marker until
  its root cause is fixed, then re-pin.

## Step 4 — pin the canonical rows in the fixture

Add the case's canonical rows to `backend/tests/jaccard_canonical.py`:
`CANONICAL_ROWS` (edge rows: seed, endpoints, kind, anchor), `CANONICAL_NODES` /
`CANONICAL_NODES_DIR` (per-direction node entries), and any `NORMALIZE_MAP` entries
(alias → canonical table, and label folds). Keep the label identity case rule in
mind — see ISSUE-5 (`_norm` case-folds only the `NORMALIZE_MAP` key lookup; the
fallback label keeps its source case, so the canonical spelling must be the
frequency-voted physical name).

## Step 5 — register the case in the harness

In `backend/tests/test_jaccard_benchmark.py`:
- append `(seed, script, direction)` to `CASES`,
- add `TARGET_FIELDS[seed]` and `SEED_TABLE[seed]`,
- pin `FLOORS[seed] = {feature: {recall: 1.0, precision: 1.0}}` for nodes, edges,
  highlights — every feature at full recall AND precision (full set equality is the
  gate). The up/down direction axis lives in `CASES`, not in `FLOORS`.

## Step 6 — run and converge

```bash
docker exec -w /app/backend gps-sql-backend python3 -m pytest tests/test_jaccard_benchmark.py -v
```

Iterate steps 2–5 until every feature of every direction is at recall = precision =
1.0 (the floor is "at least 1.0"; since M-BM1 every numerator is a true set size —
nodes recall counts realized canonical nodes, nodes precision counts realizer served
nodes — so no direction can print above 1.0). The benchmark is the regression
gate — every subsequent engine change re-runs it.

## Step 7 — the door (exit criterion, 2026-08-25)

The loop never stops mid-iteration. Every benchmark run MUST be followed by an
analysis of the diff: for each missing/extra canonical entry, identify the **reason**
and the **defect** (a real solution defect → fix the engine; a ground-truth error →
repair the doc; a known gap → record its root cause). Fix it automatically, then
re-run. **Stop only when the benchmark can no longer be improved** — i.e. every
feature of every case is at recall = precision = 1.0, or the only remaining diffs are
classified known-gaps whose root cause is already tracked as a separate, in-scope bug
(no further fix belongs in *this* iteration). A green run is a door exit; a "we'll
come back to this later" is not.

## Ordering note (2026-08-25, user ruling Q4 = A)

For a NEW feature (e.g. the L2 line-merged views), implement the feature **first**,
then write its benchmark cases against the real output — the ground truth is still
derived from SQL independently (Step 1) and merely *verified* against the now-live
output (Step 2). This is "implement-then-benchmark", not benchmark-first; the
independence rule is unchanged.

## R44 re-derivation record (2026-08-28, EXTRACTOR_VERSION 2026-08-28.3)

R44 (occurrence coverage) changed the extraction so three canonical cases went stale
BY DESIGN. They were re-derived FROM THE SQL TEXT (jaccard_canonical.py docstring
point 17); the served L2 was consulted only as the post-hoc cross-check. The
per-case derivations, so the reasoning survives apart from the fixture:

### pl downstream + bdm upstream-in-PL (BDM_ACC_LOAN_INFO_PL.sql) — statement-shape re-pin

SQL text: the script writes `INSERT OVERWRITE TABLE bdm_acc_loan_info
PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan');` at **L19**
(semicolon-terminated, no source of its own), then a standalone
`SELECT distinct a.acnw AS LENDING_REF … ;` at **L21-251**, then the job-log
`INSERT INTO TABLE rrcdm_job_log_exec_par(…)` at **L253-265** (`'${load_date}' AS
data_dt` @254, `FROM bdm_acc_loan_info` @263, `WHERE data_dt='${load_date}'` @264).

Reading the script as the writer intended (the ODPS idiom), L19 + L21-251 are ONE
write statement — which is what R44's F1 fix now extracts (one statement, TOP0; the
job-log INSERT keeps TOP2). Consequences re-derived per row:

- The bare INSERT's `"⟐ insert"` trunk @19 **no longer exists** — a bare INSERT with
  no SELECT body never has an output frame of its own once its source is the
  following SELECT. The merged statement's output VT is `⟐ output` **born at the
  SELECT@21** (the output frame IS the SELECT result set).
- **P15/V1 @19** (write leg + partition value-write) keep anchor 19: the DML write
  and the partition literal both sit on L19 in the text.
- **R1 (pl) / UBP1 (bdm↑PL)** — the partition-read redirect of
  `PARTITION(data_dt='${load_date}')`@19 into the statement's output frame — re-pin
  anchor **19 → 21**: the redirect lands on the merged statement's output frame and
  carries that frame's own line (the SELECT). The src endpoint keeps `data_dt@19`,
  the SQL occurrence line of the partition column. (Pre-R44 this edge anchored @19
  because the trunk was the ⟐insert VT born at the INSERT line.)
- **P16/V2/M1 @253/254 and P18/P22/F1 @263/264** are stmt2's own lines — invariant
  to the merge, unchanged.

Measured after re-pin: pl 7 served nodes realize all 9 canonical nodes, 9/9 edges,
6/6 highlights; bdm↑PL 3/3, 3/3, 2/2 — recall = precision = 1.0 everywhere.

### lending_ref downstream-in-SUP_M (BDM_ACC_LOAN_INFO_SUP_M.sql) — pure augmentation

R44's user ruling ("covering all occurrences of the target field is the PURPOSE of
flow-only") admits the physical-side instances of the derived-alias join-key
operands and the NOT-IN subquery container. SQL-text derivation:

1. **p2 is a single-source derived alias** — its body reads exactly one physical
   table: `FROM ods_hub_lsacmsp` @33 (subq scope) and @109 (loan_final scope), with
   the column list `SELECT podcg, poctcd, pogmab, poacb, poacs, poacx, podtao, …`
   @31/@107. Therefore every `p2.X` operand of the CONCAT join keys is an
   occurrence of an `ods_hub_lsacmsp` column at that line.
2. **The join keys** — `ON CONCAT(p2.poctcd,p2.pogmab,LPAD(p2.poacb,3,'0'),
   LPAD(p2.poacs,6,'0'),LPAD(p2.poacx,3,'0'),LPAD(p2.podtao,8,'0')) =
   p1.lending_ref` at **L41** (subq) and **L117** (loan_final). The po* operands
   are join siblings of the lending_ref key, so the closure carries per-line
   admissions for BOTH instance identities of each operand: the alias-side
   admissions (rows LFS16-23 @41, LFS45-50 @117 — pre-existing) and the
   physical-side admissions (new rows LFS80-85 @41, LFS86-91 @117).
3. **The copy ties @117** — the alias-side reads `p2.poctcd …` @117 ARE the
   physical columns, so the closure ties each @117 alias-side read onto the
   physical occurrence (new rows LFS92-103, REF@117; one copy lands on the
   physical instance whose occurrence stream includes the @41 read — dst carries
   line evidence 41 — and one on the @117-scoped physical instance).
4. **The NOT-IN container** — `AND p1.lending_ref NOT IN (SELECT DISTINCT
   lending_ref FROM bdm_evt_loan_trans a …)` @48-58, with the output column at
   **L50** and the FROM at **L52**. The subquery's `lending_ref@50` output is a
   closure member (membership SCHEMA@50, new row LFS104 — the LFS9/LFS11 ⟐subq1/
   ⟐subq pattern) and its value set feeds the enclosing subq scope's row selection
   (TABLE_FLOW@50 into ⟐subq, new row LFS105 — the LFS12 container-hop pattern one
   level deeper). New node: `⟐subq2@50` (served label `output(subq2)`, the #223
   display form; NORMALIZE_MAP folds it).

Pin mechanics for the parallel admissions: the twin edge of a join admission is
(label, line)-identical to its sibling row (one SQL occurrence, two instance
identities), so the shared endpoint is pinned label-only (`@0`) and the matcher's
used-set consumes the second parallel edge. No `pending` flags were introduced —
every new row is SQL-text-grounded by items 1-4 above.

Closure after re-derivation: 38 canonical nodes / 103 canonical edges; served 49
nodes / 103 edges — recall = precision = 1.0 on nodes, edges, highlights. The
other 18 gate cases (17 previously at 1.0 + the empty-upstream pair) re-measured
1.0000/1.0000 — no regression from the R44 walker change.

## K3 re-pin record (2026-08-29, F-D — EXTRACTOR_VERSION 2026-08-28.7)

K3 (the pixel-adjudicated sample repair) removed the stray `;` that ended the PL
bare INSERT, so the R44 record's PL section above describes a sample shape that no
longer exists: there is no "semicolon-terminated, no source of its own" INSERT@19
any more. Re-derived from the repaired text (jaccard_canonical.py docstring
point 18):

- **Statement shape** — L19-L251 are ONE statement again (TOP0 = `INSERT OVERWRITE
  … PARTITION(data_dt='${load_date}',CHARGE_DEPARTMENT='OPS_CLBS_PLoan')` + the
  `SELECT distinct a.acnw AS LENDING_REF …` body); the job-log
  `INSERT INTO TABLE rrcdm_job_log_exec_par(…)` @253-265 is **TOP1** (it was TOP2
  while the stray `;` made sqlglot count three statements). **No line moved** — the
  `;` was removed, not a line — so every @253/@254/@263/@264 pin is untouched.
- **R1 (pl) / UBP1 (bdm↑PL)** re-pin anchor **21 → 19**: the merged statement's
  output VT is born at the INSERT@19 (the statement's own first token), so the
  partition-read redirect of `PARTITION(data_dt='${load_date}')`@19 carries line
  19, not the SELECT@21 line the R44 round pinned (that 21 was the fallback's
  synthesized SELECT frame). `src` keeps `data_dt@19`. Engine cross-check: REF@19,
  flow_kind=read, into the output VT ctx=TOP0 line_start=19.
- **P16/V2 (pl) and RDP3 (rrcdm↓PL)** re-pin `stmt` **TOP2 → TOP1** (the J12-17
  write-leg endpoint check): the write leg's output VT is ctx TOP1 / line_start
  253.

Measured after re-pin: pl 9/9 edges + 5/5 highlights; bdm↑PL 3/3 + 1/1; rrcdm↓PL
3/3 + 2/2 — recall = precision = 1.0, and the R19.3 J12-17(a) write-leg problems
are gone.

### lending_ref downstream-in-SUP_M — the family-3 occurrence twins (F-D)

The R44 record's items 1-4 stand. What changed under EXTRACTOR_VERSION
2026-08-28.6/.7/.8 is that two of the six join-key operands own a SECOND
in-scope occurrence, so their occurrence twins render at their own lines
instead of the join-key line: **pogmab** @46 (`AND p2.pogmab = 'HSBC'`, subq
scope) and **poctcd** @120 (`p3.zfctcd = p2.poctcd`, the p3 join ON inside
loan_final). Re-pins: LFS29 (copy REF → alias instance @41),
LFS36/LFS56→LFS62 (belongs-to @46/@120), LFS85 (FILTER@46 into ⟐subq),
LFS91 (JOIN@120), LFS100-103 (the four cross-instance copy REFs @46/@120),
and **LFS64, re-pinned @153 → @150** (`ON RPAD(p4.iiapty,3,'')||p4.iiblno =
p1.lending_ref`). The @153 anchor came from the iiapty closure's rendering
of that join step; L153's predicate is `p5.iiapty = p4.iiapty`, never
lending_ref, so it can only serve the iiapty closure — where the same
physical relation is canonical as IID5 (`iiapty@151 → loan_final@64`,
JOIN@153). In the lending_ref closure the served graph has NO edge at 153
and the surviving join step is L150's, whose key ends in `p1.lending_ref`
and so admits under W4 (J12-20 option b).

**New rows:** LFS107 (the rollover IN-filter's filter step, anchored **@19**
— the `AND lending_ref IN (` predicate line; the earlier @22 pin was the
nested IN-subquery's own projection column, a different scope whose
belongs-to stays LFS8/LFS9) and LFS108 (the NOT-IN filter step @48).
**Removed:** LFS109 — the X2 "output column read into its own output frame"
rendering has no realization path (`_simplify_dml_edges` mints it only
behind a `tgt in dml_targets` gate, and ⟐subq1 is a CTE-body subquery's
output frame, never a DML target; the ownership fact it doubled is already
canonical as LFS9, and its membership predicate is LFS107 @19), and
LFS110/IID18 — the physical-side belongs-to twin of `p2.lending_ref`@201
plus its lending_ref-seeded twin (L201 reads `p2.lending_ref` with p2 the
ALIAS of bdm_acc_loan_info_sup @199, so the one ownership fact the text
supports there is already canonical as LFS74). New nodes: `pogmab@46`,
`poctcd@120`.

**Removed**: LFS56 (`poctcd@117 → rollover@9 REF@117`) — one of the six "@117
operand copies into rollover" rows the point-15 served-closure dump produced, the
round CR10 declared circular. SQL text refutes the flow: the L117 join's consumer
is loan_final (LFS50/LFS86-91); rollover is a sibling CTE consumed by the L41 join
and by p6 @155-156. LFS51-55 keep their rows only because the engine still renders
them — same circularity, routed to the extractor/doc owner with the removal note.

**Two engine edges are NOT canonicalized** — both were extractor defects
(owner F-C, model-witnessed because the model shares the extraction output),
and both are CLOSED by EXTRACTOR_VERSION 2026-08-28.8 (Fixes C/D): the engine
no longer mints either edge, so no canonical row exists for them, and each is
pinned by a test so the defect cannot return silently.

| edge | SQL-text refutation | resolution |
|------|---------------------|------------|
| `SCHEMA@182` bdm_acc_loan_info_sup → CHARGE_DEPARTMENT@160 | L182 is `p1.charge_department` with p1 = loan_final (L198) — the SOURCE-side column computing reserved_field7; the sup partition slot is fed by L196 `,p1.charge_department`. Family 3's "never a guessed owner" contract was violated. | **Fix D** — the @182 occurrence is owned by loan_final; pinned by `test_occurrence_twin_owner_scope.py::test_charge_department_twins_are_owned_by_loan_final`. |
| `SCHEMA@59` bdm_evt_loan_trans → lending_ref@50 | L59 `GROUP BY lending_ref` belongs to the ENCLOSING subq (the NOT-IN subquery closes at L58) whose source is p1 = bdm_acc_loan_info — pinned as LFS106. | **Fix C** — the GROUP BY occurrence is anchored inside its own scope only; pinned by `test_no_town_outside_the_not_in_subquery_scope`. |

With LFS64 re-pinned to @150, LFS107 re-anchored to @19 and LFS109/LFS110/IID18
removed, the gate is at set equality: **20 passed / 0 failed**, recall AND
precision 1.0000 on all 20 cases (`lending_ref↓SUP_M` 105/105 edges,
highlights 26/26 after the F-K adjudication; `iiapty↓SUP_M` served from its
own closure, IID5). *(Measured at `EXTRACTOR_VERSION 2026-08-28.8` and
re-verified 2026-08-29; the in-flight R44 Fix A stage-1 work on
`lineage.py` — the derived-holder single-source gate — re-reddens
`lending_ref↓SUP_M` nodes/precision until it is re-adjudicated, so re-check
this row against the tree you are standing in.)*

### line-merged invariant (test_l2_line_merged_benchmark.py) — adjudicated

The rule-4 self-loop check was the pre-L-E5 form (`len(les) > 1`);
`l2_builder.build_line_merged_edges` carries the later ruling: a self-loop is
absorbed only into the line's NON-SELF edge(s), and a line of only self-loops keeps
every one of them (two distinct tables' loops are each their own table's sole
edge). The check is amended to that semantics — the builder is not asked to dedup
harder, and the invariant's intent (a table's loop must never silently disappear
among a line's other table-pair edges) is unchanged. Its one live trigger was the
`SCHEMA@59` defect above; once that is fixed, line 59 carries exactly one self-loop
(the genuine LFS106 GROUP-BY twin) and both the old and the amended rule keep it.
