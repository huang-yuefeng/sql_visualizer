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
mind — see ISSUE-5 (`_norm` case-folds; the canonical spelling must be the
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
1.0 (the floor is "at least 1.0"; a direction may print above 1.0 when one response
node realizes several same-label canonical entries). The benchmark is the regression
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
