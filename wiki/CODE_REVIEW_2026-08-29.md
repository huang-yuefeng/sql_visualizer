# Code Review — 2026-08-29 (post-release v3.3.191)

**Teams:** 4 review teams over `ca653a4..de7725c` (R1 extractor/lineage, R2 services/routers,
R3 frontend, R4 tests + docs + release tooling) + 2 adjudication teams (AD1, AD2).
**Base range:** `ca653a4` (v3.3.190 restore) → `de7725c` (release.sh smoke port) → `2c05e1a`
(`[release] v3.3.191`).
**Companion records:** `wiki/CODE_REVIEW_2026-08-28.md` (uncommitted-delta review that fed this
one), `wiki/CODE_REVIEW_PENDING_2026-08-27.md` (the standing consolidated ledger).
**Method:** findings first, then adjudication — a reviewer may not both report and dispose. Each
finding was re-measured by an adjudication team against the SQL text / the served payload / the
extracted tree before it was accepted, refuted or deferred. No finding was fixed on the
reviewer's word alone.

**Status of this file:** the R4 (tests/docs/tooling) rows below are complete — fix team G5
implemented and verified them in the same working session. The R1/R2/R3 rows carry the
adjudicated verdict and are marked **fix in flight (v3.3.192)** where the owning fix team had not
landed when this record was written. AD2's numeric verdicts are recorded as measured; the
per-finding IDs live in the review transcript and are referenced here by the row names the teams
used. **§6–§9 (added 2026-08-31)** record the 2026-08-30/31 rounds — the Field Story audits, the
multi-user audits and the hardening batch they produced, and the R40.13 acceptance cross-check.
**§10–§16 (added 2026-09-01)** record the v3.3.195-wave rounds that landed after that — FSC-2
model persistence, the H11 MERGE-column connectivity round, the container-PROVENANCE relay, the
X1/X2 review rounds and the R40.13 cross-check round 2. Every code claim in those sections was
re-verified against the working tree by grep/read at
writing time; where a measurement lives only in the session transcript and has no repo artifact,
the row says so explicitly rather than citing a number nothing in the tree can reproduce.

---

## Verdict

Of the 39 findings raised (R1 ×11, R2 ×5, R3 ×7, R4 ×16), the adjudicated outcome is:
**confirmed and fixed in this batch (R4, 16 of 16)** · **refuted** (R1's own proposed fix and one
R2 deletion — see AD1) · **deferred with reason** (the extractor-defect residue R4's waiver table
records, filed for v3.3.193) · **fix in flight (v3.3.192)** (the remaining R1/R2/R3 rows owned by
G1–G4). No finding was closed by argument alone: every accepted one carries a measurement or a
file:line, and every refuted one carries the measurement that refutes it.

---

## 1 · Findings ledger

### R1 — extractor / lineage (11 findings)

| Row | Area | Verdict | Disposition |
|-----|------|---------|-------------|
| R1.1 | derived-product admission admits a holder that does not deliver the searched table's value | confirmed — fix in flight (v3.3.192) | G1: `_holder_is_derived_single` (lineage.py, R44 Fix A stage 1) — a container qualifies only when its scope reads exactly ONE original physical table whose identity is the target; EXISTS bodies are row-selection, not row-source |
| R1.2 | occurrence twin minted outside its own paren scope | confirmed — fixed | F-E2 Fix C/G (2026-08-28.8); pinned by `test_occurrence_twin_owner_scope.py::test_no_town_outside_the_not_in_subquery_scope` |
| R1.3 | wrong owner: last-dot-part matching resolved a group to the first same-field var | confirmed — fixed | F-E2 Fix D; pinned by `::test_charge_department_twins_are_owned_by_loan_final` |
| R1.4 | phantom pairing: a duplicate registration stole a genuine occurrence's line | confirmed — fixed | F-E2 Fixes E/F |
| R1.5 | expression fragment reaching the field namespace minted a physical field | confirmed — fixed | K3 auto-named stamp; pinned by `::test_fragment_named_column_is_stamped_auto_named` |
| R1.6 | `is not False`-class assertions hiding unmatched closures (tests, filed under R1 by the extractor team) | confirmed — fixed | R4 L; see R4 rows |
| R1.7 | R1's proposed fix for the twin-waiver no-op | **rejected as complete** (AD1) | see §2 |
| R1.8–R1.11 | remaining extractor rows | fix in flight (v3.3.192) | owned by G1; the ones that turned out to be real model gaps are also recorded in R4's waiver table as v3.3.193 material |

### R2 — services / routers (5 findings)

| Row | Area | Verdict | Disposition |
|-----|------|---------|-------------|
| R2.1 | `get_level2_graph` writes `search_matched` only as `False` (absent ⇒ matched) — the contract is undocumented and callers assert it wrong | confirmed — fixed | documented at the assertion sites (`test_k4_rulings_fb1.py`, `test_alias_seed_expansion.py`); the service contract itself is unchanged by design |
| R2.2 | proposed deletion of a fold/group-admission branch as dead code | **refuted** (AD1) | see §2 — 53 twins depend on the group admission |
| R2.3 | workspace-id hygiene in service-layer tests | confirmed — fixed | R4 (fabricated `probe` workspace id) |
| R2.4 | filter/CTE index guards vacuous on an empty index | confirmed — fixed | R4 L |
| R2.5 | remaining service row | fix in flight (v3.3.192) | owned by G2 |

### R3 — frontend (7 findings)

| Row | Area | Verdict | Disposition |
|-----|------|---------|-------------|
| R3.1 | canvas clipping of the seed chip under the merged-view filter | measured — fix in flight (v3.3.192) | see §2 (AD2 numbers) |
| R3.2–R3.7 | remaining frontend rows | fix in flight (v3.3.192) | owned by G3 |

### R4 — tests / docs / release tooling (16 findings) — ALL FIXED in this batch

| Row | Finding | Fix | Where |
|-----|---------|-----|-------|
| R4-H (M-H) | the R44 twin waiver was a corpus-wide no-op: the predicate matched every dotted non-output column, so 14 live `column_connectivity` findings were waived while only some of its members carried the `OCCURRENCE` marker at all | predicate tightened to require the `OCCURRENCE` marker + asserted `waived ⊆ occurrence_twins`; the 14 findings the tightening hands back are adjudicated one by one in `_ADJUDICATED_CONNECTIVITY` (7 false positives documented, 7 recorded as v3.3.193 defects), and every entry must keep firing or the test fails | `backend/tests/test_graph_integrity.py` |
| R4-M (sentinel) | `test_alias_seed_expansion` could silently skip the whole module if the `_ALIAS_SEED_EXPANSION` sentinel disappeared — and the probe swallowed import-time crashes | ungated `TestSentinel` tripwire + per-class `skipif` (never module-wide) + `except` narrowed to `(ImportError, ModuleNotFoundError)` | `backend/tests/test_alias_seed_expansion.py` |
| R4-M (workspace) | `_build_l2_graph("probe", …)` wrote graph caches into the shared `/tmp/workspaces/probe` forever | `uuid4`-uniqueness via `create_workspace` + `delete_workspace` in `finally`; stale `probe/` residue deleted | `backend/tests/test_occurrence_twin_owner_scope.py` |
| R4-M (coverage) | DDL files returned silently (indistinguishable from never-run) and an empty sample corpus passed the sweep vacuously | `pytest.skip("DDL file …")` + collection-time `assert any(_all_sample_files())` | `backend/tests/test_graph_integrity.py` |
| R4-M (doc residue) | `BENCHMARK_CASE_BUILD_METHOD.md` held a broken string-replace: duplicated fragment, mid-sentence break, rows listed as new that were removed, a stale `@22` anchor and a stale `18 passed / 2 failed` | section rewritten as coherent prose at the final adjudicated state (LFS64 @150, LFS107 @19, LFS109/LFS110/IID18 removed, 20 passed / 0 failed, both extractor defects closed) | `tools/BENCHMARK_CASE_BUILD_METHOD.md` |
| R4-M (release gate) | `release.sh` shipped on a skipped pre-flight, a warned-but-ignored container suite, a smoke `curl` that never cleaned up, a readiness loop with no timeout message, and an undefined `$YELLOW` | all six (a)–(f) hardened: pre-flight fails hard with instructions when no runner (venv → `docker exec gps-sql-backend`, local so the offline rule holds), container pytest exits non-zero, `curl … \|\| { docker rm -f gps-test; exit 1; }`, readiness timeout prints + aborts with logs, `$YELLOW` defined, RELEASE.txt `COMMIT` documented as the pre-release-commit HEAD | `release.sh` |
| R4-M (changelog) | `SNAPSHOT_CHANGELOG.md` read a dated entry *below* "How to add an entry" and out of date order; a stale snapshot count | restructured newest-first with "How to add an entry" LAST; "All 41" → "All 109" | `SNAPSHOT_CHANGELOG.md` |
| R4-L ×8 | small test-quality defects: `is not False` tautologies, an assert that could not fail (selected by its own filter), an unexecutable source-text assert, vacuous negative loops on empty results, an undocumented magic count | see the itemised table in §3 | 6 test files |

---

## 2 · Adjudication highlights

### AD1 — the A/B/C/D/E/F verdicts

* **R1's own fix was rejected as complete.** The fix as proposed removed the symptom (the waived
  checker findings) without narrowing the predicate that caused them; accepting it would have
  left the waiver free to re-absorb future findings silently. The adjudicated form is the
  tightened predicate **plus** the per-finding adjudication table, so each of the 14 has its own
  verdict and none can be re-absorbed by a signature.
* **C deletion refuted — 53 twins depend on the group admission.** R2 proposed deleting the
  group-admission branch as dead weight. Adjudication re-measured instead of arguing: the branch
  is the only thing that lets 53 occurrence twins inherit the clause their own label lost, and
  removing it re-darkens those lines. Deletion refused; the branch stays, with the dependency now
  written down.
* **D, E, F** — the wrong-scope / phantom-pairing / fragment-field findings were confirmed by
  direct measurement (the twin's line sits outside the group's own paren scope; a duplicate
  registration consumed a free line a genuine occurrence needed; a fragment-named field reached
  the field namespace). All three are folded into `EXTRACTOR_VERSION 2026-08-28.8` and pinned by
  `test_occurrence_twin_owner_scope.py` / `test_filter_twin_edges.py`.

### AD2 — the measured verdicts

AD2 replaced argument with measurement on the two rows the review teams disagreed about:

* **9 mis-anchored keys.** Nine canonical benchmark keys were anchored on a line their SQL text
  does not support (a carrier chosen by fold order rather than by the searched field's own
  occurrence). Each was re-derived from the SQL text alone and re-pinned; the two rows that
  turned out to have no realization path at all were removed rather than re-anchored. Recorded
  in `jaccard_canonical.py` (F-J/F-K notes) and in `tools/BENCHMARK_CASE_BUILD_METHOD.md`
  §"lending_ref downstream-in-SUP_M". Gate after re-derivation: **20 passed / 0 failed**, recall
  AND precision 1.0000 (re-run by G5 on 2026-08-29 at `EXTRACTOR_VERSION
  2026-08-28.8`; the in-flight Fix A stage-1 work on `lineage.py` re-reddens
  `lending_ref↓SUP_M` until it is re-adjudicated — see §5).
* **Canvas clipping numbers.** The clipping claim was measured against the served payload rather
  than estimated: the seed chip renders below the legibility floor at the default zoom in the
  merged view, with the affected-node/visible-node counts recorded in the AD2 transcript
  (front-end ownership G3 — fix in flight, v3.3.192; the measurement, not the opinion, is what
  this record keeps).

---

## 3 · R4-L itemised (the small test-quality rows)

| Finding | Fix | Where |
|---------|-----|-------|
| `res.get("search_matched") is not False` could never fail | the served level2 response writes `search_matched` **only** as `False` (absent ⇒ matched), so the honest form is `res.get("search_matched", True) is True` — a literal `is True` would have failed on the real contract | `test_k4_rulings_fb1.py` (×2), `test_alias_seed_expansion.py` (flagship) |
| `assert twin.line_start == line` could not fail — the twins were selected by that line, and `VariableDependency` carries no anchor payload to assert instead | deleted, comment rewritten to point at the L2 test that really pins own-line anchoring (`{37, 113} ⊆ closure highlight lines`); `not filt[0].containment` kept as the one meaningful edge-level assert | `test_filter_twin_edges.py` |
| source-text assert on an unreachable seeded path | assert dropped (R29 item 8 makes the field-query path unreachable through the service layer, so it could only ever re-test the source, not the system) and replaced with the behaviour the limitation actually implies — an L1 built for a field query carries only script/table nodes, never a field node | `test_k4_rulings_fb1.py::test_l1_builder_seed_is_case_insensitive` |
| `assert res.get("error") is None` on a builder that never emits `error` | dropped as tautological; **kept** at the one site where the key IS producible (`get_level2_graph` returns `{"error": …}` for an unresolvable script, `dataflow_service.py:476`) — the reviewer's "tautology" held for only one of the two sites | `test_k4_rulings_fb1.py` |
| negative/vacuous loops: a broken extractor that produced nothing passed | `assert fields` / `assert twins` / `assert ti` guards added before every loop that asserted the absence of something | `test_k4_rulings_fb1.py`, `test_occurrence_twin_owner_scope.py`, `test_folder_index_cte.py` |
| `total_columns == 52` had no driver statement at the assert | breakdown verified from the extracted tree (26 source reads + 16 write twins [stg_orders ×5, stg_customers ×4, analytics_orders ×6, daily_summary ×1] + 2 GROUP BY twins + 8 occurrence twins = 52) and written at the assert | `test_full_http_journey.py` |
| one index case never driven through the real entry | `test_cte_field_search_through_create_search` added — asserts the intersection `create_search` actually computes, not its two halves | `test_folder_index_cte.py` |

---

## 4 · Deferred to v3.3.193 — extractor defects waived-with-note (NOT fixed here)

`test_graph_integrity.py::_ADJUDICATED_CONNECTIVITY` records seven `column_connectivity` findings
whose belongs-to edge is genuinely missing because `dependency_graph` Phase 4d-gb admits only the
`GROUP BY` clause and the `OCCURRENCE` marker; MERGE ON / MERGE UPDATE SET / MERGE WHEN / JOIN ON
fall between the two. Each is waived with the defect stated, and each entry **must keep firing** —
the moment the fix lands the test fails and names the entries to delete.

| Column | Clause | Note |
|--------|--------|------|
| `gps_transactions.amount` | MERGE UPDATE SET | genuine column; the @18 occurrence twin (same TOP0) carries the belongs-to edge, so the rendered chip stays connected |
| `gps_transactions.fee_amount` | MERGE UPDATE SET | no sibling registration |
| `gps_transactions.txn_id` | MERGE UPDATE SET | no sibling registration |
| `gps_transactions.settlement_date` | MERGE UPDATE SET | the @21 occurrence twin carries the edge |
| `gps_transactions.net_amount` | MERGE WHEN | no sibling registration |
| `gps_transactions.currency_code` | MERGE WHEN | no sibling registration |
| `gps_transactions.merchant_id` | JOIN ON | the @106 sibling (in `:join:txn`) carries the edge |

The other seven findings in the same table are **false positives** (the check's belongs-to
premise does not hold: a renamed USING projection, an aggregate born inside a derived scope, a
bare GROUP BY key owned by a derived container) and are documented as such — emitting the edge
for them would fabricate a schema fact.

---

## 5 · Cross-team interference observed during the fix batch

* G1's in-flight `lineage.py` work (R44 Fix A stage 1, `_holder_is_derived_single`) changed the
  L1/L2 flow projection under the fix batch:
  `test_full_http_journey.py` — the downstream L1 no longer carries `stg_orders`
  (`{table_name} == {crm_customers, stg_orders, stg_customers, analytics_orders}` fails, actual
  misses `stg_orders`); `test_occurrence_twin_owner_scope.py::TestRfnBirthLines` —
  `repay_acct_no`'s derivation line 364 went dark. Both are G1's to re-adjudicate; G5 did **not**
  touch either expectation, because masking a directional-flow regression behind a test edit is
  the failure mode this review exists to prevent.
* `test_graph_integrity.py`'s tightened waiver + adjudication table is measured against
  `EXTRACTOR_VERSION 2026-08-28.8`; when G1 bumps to `.9` the counts must be re-measured and the
  waiver table re-verified (the "must keep firing" assert will name any entry the fix retires).

---

## 6 · Field Story audits (FSA/FSB/FSC) and the G6 rules rewrite (2026-08-30/31)

Three audits of the Field Story classification, run in that order. Each widened the sample; the
third is the one that decided the rewrite.

| Audit | Scope | Headline result | Disposition |
|-------|-------|-----------------|-------------|
| **FSA** | Field Story stage classification, EAST5 | **167/597 told steps = 28% true of the searched field** (birth 3/49, read 0/95, consumed 32/267, joined 51/105; written/reappears/filtered 100%). Ground truth = the script text + a hand-verified token/alias model built independently of the module. | **Fixed by G6** — see below |
| **FSB** | flow-only targeting | 168/168 seeds; 45.4% occurrence-index on CASE-chain fields; recall 80.3%. *Measured in the working session — the case list is transcript-only, no repo artifact.* | fed the FSC design |
| **FSC** | corpus-wide, 3,922 `(table, field)` pairs | median occurrence-index 0%; three structural holes — **(a)** 24.1% of pairs have no flow / owner-less bare columns, **(b)** the closure is not a pure function of the script (snapshot integrity), **(c)** recall p10 33%; plus a 1.1 s per-field perf floor on the RFN-scale sample. *Measured in the working session — transcript-only.* | **v3.3.195-program**, not a v3.3.194 fix — the holes are engine-shape, not display-shape |

### G6 — the rules rewrite (landed, frontend-only)

`frontend/src/utils/fieldStory.js` re-ruled under ONE governing idea (file header, "THE ONE
GOVERNING IDEA"): **a step is told only when the payload carries FIELD-level provenance for the
searched field** — an edge endpoint that IS one of the searched field's chips. Where the payload
is silent about the field, the story is silent too: the step is DROPPED, never re-anchored onto a
line the field was not on. Four rules changed (`Fix H` + three `Fix M` sub-rules, `fieldStory.js`
:158-171, enforced at `:354`):

1. **Fix H (`consumed`)** — the stage had no field-leg requirement and its ⟐output exclusion
   tested `type === 'output_table'`, a type absent from served payloads (real routing
   intermediates are `intermediate_table`) — the guard was dead code, so every write leg in every
   closure landed in `consumed`, including each field's own AS-alias birth line. Now: the routing
   family is matched by type AND the `⟐` name marker; a value leg must be SOURCED by one of the
   field's own chips; the leg resolves through the routing intermediate's single outgoing write
   leg (no single leg → untold, never guessed) — own table ⇒ **birth**, other table ⇒
   **consumed** at the consuming DML line.
2. **Fix M (table-path)** — no chip endpoint ⇒ no step (the audit's 191 TABLE-PATH + 52 PHANTOM
   steps).
3. **Fix M (read)** — a read needs the chip to SOURCE the leg (`compound → chip` value copies
   measured 8/8 wrong) at the chip's own `line_start`; joined/filtered need a line that is
   neither the compound's anchor nor, for JOINISH types, the chip's own line.
4. **Fix M (birth)** — `highlight_line === the table's line_start` is no longer the birth test
   (it is the FROM/JOIN anchor for a source table — 46 fake births); a source-side field has NO
   birth stage; a birth line absorbs the other chip edges on that line.

**Re-run of the SAME audit over the SAME 117 EAST5 pairs: 207/216 = 95.8%** (birth 61/61 — up
from 3/49, read 34/34, written 63/63, reappears 14/14, filtered 4/4, joined 10/13, consumed
21/27), **0 H defects** (was 138), 597 → 216 steps, 116/117 stories non-empty. Scored by the
audit's own published engine unchanged the figure is 69% — the whole delta is that engine's birth
branch, which had no OK case for a target column's AS-alias line; the amendment rules (Fix 1c)
that the AS-alias line IS the birth. The 9 residual M defects are NOT client-fixable (6× a
SELECT-output alias the walker attributed to a SOURCE table; 3× a COMPUTED edge addressed to the
wrong output chip) — backend follow-up, recorded at the R40.12-A row. Full numbers:
`wiki/REQUIREMENTS_TRACEABILITY.md` R40.12-A, `CLAUDE.md` #37 amendment.

## 7 · Multi-user audits (M1/M2/MSC) and the hardening batch (2026-08-31, landed)

The audits found one CRITICAL, one HIGH and a set of contract breaks; the batch below is their
output. Every row carries its own tree verification. New suites: **104 tests** across
`test_incremental_index.py` (29), `test_multiuser_workspace.py` (19), `test_multiuser_sessions.py`
(14), `test_audit_trail.py` (16), `test_heavy_gate.py` (12), `test_logger_broadcast.py` (14), plus
`test_participant_reads.py` (9).

| Row | Finding | Verdict / fix | Tree proof |
|-----|---------|---------------|------------|
| **MSC-1** | **CRITICAL.** `HeavyGate` kept per-call state on the MODULE-LEVEL SINGLETON every heavy-op endpoint shares; a refused (409) entrant overwrote the holder's `_acquired` before the holder unwound, so neither `__exit__` released and the module global `_busy` stayed True FOREVER — every search, any user, any workspace answered 409 "system busy" until the container restarted. Reproduced live at 0% CPU after one concurrent burst. | **fixed** — the acquisition lives on a per-call `_GateToken` holding its OWN acquired/released flags, kept on a `threading.local` LIFO stack; a refused entrant on another thread can never reach the holder's token. The singleton and the one global `_busy` stay (serialization unchanged), only the bookkeeping moved. | `backend/app/services/heavy_gate.py:13-19,45-70,79-113`; `tests/test_heavy_gate.py` (12 — the deterministic wedge sequence, 8-thread hammer, exception-inside-gate) |
| **torn read** | Every index/cache/meta write was truncate+write, so a concurrent participant reader could see a half-written file — an intermittent 500, or a silently EMPTY index served as the truth. | **fixed** — `app/services/atomic_io.py` (`atomic_write_text`/`_bytes`: unique temp + `os.replace`); every index-layer and graph-layer writer routes through it; meta writes are a compare-and-swap under `_meta_cas_lock`. Proof has teeth: the same harness with the atomic write REMOVED reproduces the tear. | `atomic_io.py:26-51`; callers `folder_index_service.py:13,403,432`, `dataflow_service.py:448`, `filter_service.py:358`, `audit_service.py:34`; `workspace_service.py:169,188-211` (CAS); `tests/test_multiuser_workspace.py` (19 — matrix, capability-URL share path, torn-read + no-atomic control, catch-up 409 ×2 users, meta CAS, isolation) |
| **#380 follow-up (AD2-A)** | Participants had no read path for the tree or the index, so opening a shared workspace meant re-scanning. | **fixed** — `GET /workspace/{id}/tree` + `GET /workspace/{id}/index` serve the PERSISTED artifacts (no re-scan, no re-extract, no membership side effect); missing/corrupt cache → 409 / `{}`, never 500; the creator's open refreshes them, a participant gets an informational hint. Creator-only `POST /scan` + `/index` unchanged. | `routers/workspace.py:273-360`; `routers/dataflow.py` search/`l2` reads; `frontend/src/api/client.js:200,206`; `tests/test_participant_reads.py` (9) |
| **catch-up gate** | A search during a re-index answered from the PREVIOUS index — a field existing only in a just-added script came back as a false "not queried by any script". | **fixed** — an in-process catching-up registry; index-derived searches answer an explicit retry-able 409 for that window; the creator auto-fires the re-index on a stale open, the UI shows "Catching up: N changed script(s)…", search is withheld and replayed when the run ends. | `routers/dataflow.py:213-218,516-520`; `folder_index_service.py:2373-2398`; `DataFlowApp.jsx:468-490,697-722,1456-1470`; `tests/test_incremental_index.py:665`, `test_multiuser_workspace.py:641,664` |
| **MSC-3** | The History panel labelled itself "who did what" but held exactly ONE record (`workspace_created`) no matter what a participant did — #285 had dropped visit logging and the other actions were never written. | **fixed** — the full action set is now written (`workspace_created`, `visit_start`, `search`, `l2_opened`, `layout_saved`, `visit_end`, creator `scan`+`index`), real sessions only, atomically appended, and BOUNDED at the last 200 records under a per-workspace `flock` (the MSC-5 views.json lesson). Note: workspace CLOSE is recorded as `visit_end`, not as a `close` action. | `services/audit_service.py:13-20,47,118-159`; `routers/workspace.py:50-80,118,216,240,369,404,481`; `routers/dataflow.py:278,300,465`; `tests/test_audit_trail.py` (16) |
| **MSC-6** | The SSE log registry kept ONE ref-counted queue per WORKSPACE, so two participants (or two tabs) SPLIT the stream — every pushed line was `put` exactly once and drained by exactly one reader (a 13-line diagnostic block reached alice as 1 line and bob as 0). Each idle stream also parked a default-executor thread indefinitely. | **fixed** — the registry is a fan-out: one bounded queue per SUBSCRIBER (`_log_queues[ws] = {consumer_id: ConsumerQueue}`), every producer line delivered to ALL of them, bounded 500/consumer with drop-oldest, no parked executor thread. | `services/logger.py:7-13,33-60,127-150,178-238`; `routers/logs.py:34`; `tests/test_logger_broadcast.py` (14) |
| **L2 child "×" routing** | The child "×" called a `DELETE …/views/{id}/children/{childId}` route that was never implemented — it 404'd for EVERY role, so no L2 child could ever be removed. | **fixed** — `deleteViewChild` routes to `DELETE /workspace/{id}/views/{childId}`, the route that exists. | `frontend/src/api/client.js:304-313` → `deleteView` `:258`; backend route `routers/dataflow.py:337`; call site `DataFlowApp.jsx:1520-1523`; `api/__tests__/client.test.js:114-143` |
| **role-gated UI** | One button read "Delete Workspace" for a participant whose action only removed the workspace from their own list. | **fixed** — labelled by role (creator "Delete Workspace" / participant "Remove from my list"); the per-view "×" is creator-only (`canManageViews`); there is NO manual re-index control for anyone (user ruling 2026-08-31) — the automatic content-hash catch-up is the only re-index UI. | `components/WorkspacePanel.jsx:11-13,113-127`; `components/ViewBar.jsx:10-13,42,67`; `DataFlowApp.jsx:1519`; `WorkspacePanel.test.jsx:34-47`, `openExistingFlow.test.jsx:201-228` |
| **scale** | — | 5 participants hammer the read paths while the creator re-indexes twice: zero 5xx, zero empty/shrunk index reads, every catch-up 409 inside the re-index window, p95 latency < 10 s, no cross-user view bleed. | `tests/test_multiuser_sessions.py:420-540` (14 — lifecycle, forged/absent cookies on every endpoint class, capability isolation, the scale read-hammer) |

**Deferred / pending a user ruling (NOT fixed here):**

* **Shared vs per-user views** — R31.4's "one shared current state, last-writer-wins" is now
  load-bearing for the participant read path. Whether views should stay workspace-shared or become
  per-user is a PRODUCT question, not an implementation defect; it needs a ruling before anyone
  builds on either answer.
* **The `#` boundary class** — the R40.13 lookaround covers `[A-Za-z0-9_$]` only, so `#` is a
  boundary character and `p_dt#x` matches `p_dt`. Measured 0 `$`- or `#`-joined identifiers across
  the whole `samples/` corpus, so the omission has zero effect today; changing the class needs a
  new user ruling, never a silent amendment (see the R40.13 design section).
* **`_write_meta_cas_locked`** (`workspace_service.py:208-210`) hand-rolls its own
  temp+`replace` instead of calling `atomic_io` — same shape, but no OSError cleanup and outside
  the shared helper. Cosmetic consistency item, not a tear risk; left for the release-gate pass.

## 8 · R40.13 acceptance — the 10-difficult-case cross-check (2026-08-31, DONE)

The string-match diff layer was cross-checked against 10 difficult cases, **62 SQL lines
adjudicated**: **36 correct-covered, 11 correct-missed, 11 wrong-missed, 4 wrong-covered.**

**The layer itself PASSED** — every band it painted was a true statement about the difference
between the naive grep baseline and the engine's flow closure, which is all AC1/AC7 claim.

**Acceptance FAILED on ENGINE closure defects**, not on the layer. Three root causes:

| Root cause | Class | State at writing |
|------------|-------|------------------|
| **RC-A** | closure defect, class A | **ledgered for v3.3.195** — not scheduled for v3.3.194; still ledgered at the 2026-09-01 update (see §15 for the round-2 adjudication) |
| **RC-B** | closure defect, class B | ~~fix in flight (G7)~~ → **FIXED by G8 (2026-08-31)** — §11 |
| **RC-C** | closure defect, class C | ~~fix in flight (G7/G8)~~ → **FIXED by G7 (2026-08-31)** — §12 |

> **Provenance note.** The 10 case scripts, the per-line verdicts and the RC-A/B/C definitions
> live in the working-session transcript; no repo artifact records them yet. The team-internal
> finding is recorded here at the confidence the tree supports — the layer's implementation and
> its 42 tests are verified in the tree (`frontend/src/utils/stringMatch.js`,
> `stringMatch.test.js`, `SqlPanel.test.jsx`, `fieldStoryBar.test.jsx`), the adjudication counts
> and root-cause classes are not. When G7/G8 land, the RC-C/RC-B rows should be replaced by the
> repro scripts and the before/after closure diff; until then this section is the only record.

## 9 · Still in flight at the time of writing (2026-08-31)

Recorded here so the release gate knows what to re-check; these are NOT landed as this record was
written.

| Item | Owner | Where it will land |
|------|-------|--------------------|
| G7 — extractor RC-C closure fix (from §8) | G7 | `variable_extractor_v2` / `dependency_graph`; expect an `EXTRACTOR_VERSION` bump (currently `2026-08-28.9`) and a snapshot rebaseline — see the PENDING entry in `SNAPSHOT_CHANGELOG.md` |
| G8 — RC-B closure fix | G8 | same surface as G7 |
| P2 — fit floor + panel header | P2 | frontend (`useCytoscapeGraph` / `layoutCore` / `app.css`) |
| H8 — backend feature, scope not recoverable from the tree | H8 | flagged for the release gate — the working tree carries no H8-tagged change |
| H9 audit trail, H10 SSE broadcast | landed | these two DID land — §7 rows MSC-3 and MSC-6; listed here only because they were briefed as in flight |
| AD3 program — the corrected spec, the −64%-shrink re-derivation and the 72-row re-derivation, the RFN-scale perf flags | v3.3.195-program | the −64% / 72-row figures are transcript-only and need their own record before they are actionable |
| FSC's three structural holes (§6) | v3.3.195-program | engine-shape work, not display |

> **2026-09-01 update.** G7 and G8 HAVE landed — RC-C is §12, RC-B is §11 (the multi-anchor fold
> whose count the PROVENANCE re-pin settled), so the §8 "fix in flight" rows below are closed.
> §10–§15 record the v3.3.195-wave rounds that landed after this file's §6–§9 were written: FSC's
> snapshot-integrity hole (§10, FSC-2), the H11 MERGE-column connectivity round (§11), the
> container-PROVENANCE relay round (§12), the X1/X2 review rounds (§13–§14), the R40.13
> cross-check round 2 (§15) and the ledger items that landed alongside them (§16). H8 and P2 are
> still not recoverable from the tree at this update.


---

## 10 · V6 — FSC-2: the physical model is persisted beside the graph cache (v3.3.195 wave, LANDED)

FSC's hole (b) — "the closure is not a pure function of the script" — was a snapshot-integrity
defect, and it is the one this round closes. The physical model the strict table.field walker
consumes was built from the analysis dict when an analysis cache was present (the `alias_of`
extraction truth) but from the cached GRAPH JSON when it was not, and the graph cache serialises
nodes without `alias_of`, so that second form fell back to `physical_model`'s label-keyed alias
rule. Same SQL, two different models, decided by WHICH cache survived:

> Measured on `samples/sql_sample_v1/BDM_ACC_LOAN_INFO_RFN.sql`: **28 of 74 `alias_by_var_id`
> pairs** differ between the two input forms — e.g. var `15b561ec4099c7c3` →
> `bdm_acc_loan_info` from the analysis truth vs `ODS_IFAI_FCLETWK` from the label-rule guess;
> SUP_M **4 of 14**. `tests/test_l2_snapshot.py` builds through `_build_l2_graph` on
> never-indexed workspaces, so its second (filtered) build always took the graph-rebuilt branch:
> the committed baselines encoded the lossy variant, pinned only by PYTHONHASHSEED.

**The fix is persistence, not a smarter fallback** — the build that writes a graph cache also
writes the alias truth of the SAME analysis beside it, and a graph-cache hit that cannot rebuild
the model from an analysis cache re-derives the model from that artifact instead of guessing by
label.

| Row | What landed | Tree proof |
|-----|-------------|------------|
| **the artifact** | `cache/model_{cache_key}.json` — `{format_version, extractor_version, cache_key, alias_count, alias_of}`; `MODEL_CACHE_PREFIX = "model"` lives in `graph_service.py` (not `cache_keys.py`) because both consumers already take their graph-cache contract from the graph-serialization module; its own `MODEL_CACHE_FORMAT_VERSION = 1` is independent of the graph cache's `format_version` | `backend/app/services/graph_service.py:364-371` (prefix + contract version), `:374-391` (`extract_alias_of` — non-empty entries only, insertion order = variable order), `:393-417` (`write_model_cache` — atomic via P1's `atomic_write_text`, called from the SAME build that wrote the graph, from the SAME analysis dict, so it can never describe a sibling's graph), `:419-444` (`load_model_cache` — every guard failure returns `{}`), `:446-470` (`graph_with_alias_of` — SHALLOW node copies, never mutates the served payload) |
| **the read path** | on a graph-cache hit the model is built from the analysis cache when present and current → else the persisted alias truth → else the cached graph data (the pre-FSC-2 label-rule fallback, kept for caches written before the artifact existed — no hard break) | `backend/app/services/l2_builder.py:196-198` (path), `:240-266` (the three-step preference ladder), `backend/app/services/dataflow_service.py:516-521` (path), `:567-584` (the same ladder, mirror) |
| **the write path** | every build writes the artifact, EVEN for an alias-free script — the file's presence is what says "this graph cache carries its truth", which is what keeps the old-cache fallback test meaningful | `l2_builder.py:314-321`; `dataflow_service.py:634-641` |
| **purge posture** | `purge_workspace_caches` deliberately does NOT delete `model_*.json`: the reader requires the file's own contract version, extractor version AND cache_key to match, so keeping it buys no staleness risk while keeping the FSC-2 guarantee intact — purging it would reintroduce the hole the artifact closes | `backend/app/main.py:74-83` (docstring) + `:101-102` (the deliberate absence from the glob list); tests `test_model_persistence.py::test_purge_workspace_caches_keeps_the_model_artifact`, `::test_reindex_keeps_the_model_artifact_and_rewrites_it_on_next_l2` |
| **the divergences → 0** | the graph-rebuild path's `alias_by_var_id` becomes the analysis-cache model's; the WHOLE `PhysicalModel` is deep-equal (alias map, entity map, table names/roles/alias views, field occurrences, edges, occurrence index) | `tests/test_model_persistence.py:241` (`test_fsc_repro_graph_rebuild_path_matches_analysis_truth`), `:279` (`test_persisted_model_is_byte_identical_to_the_analysis_model`) |
| **the user-visible fix** | an alias-qualified seed (`a.cust_no`) resolved through the model's `alias_by_var_id`, so the lossy variant left NO seed → `search_matched: false` and the WHOLE graph as the answer. Pre-FSC-2: RFN `a.cust_no` served the full **1053-node / 6764-edge** fallback instead of the **78-node / 221-edge** closure; SUP_M `p3.lending_ref` **219/679** instead of **9/13**. Both spellings (`a` and `A`) are pinned | `tests/test_model_persistence.py:390-411` (the measured comment + the parametrised seeds), `:403` (`test_alias_seed_searches_no_longer_lost_to_full_graph_fallback`) |
| **byte-identity + history-independence** | the analysis-cache path and the persisted-model path serve the same BYTES on RFN + the three other alias-bearing samples, and the answer does not depend on the caches' creation history | `tests/test_model_persistence.py:333` (4 scripts, the snapshot seeds), `:355` |
| **cross-seed stable** | PYTHONHASHSEED 0–3 produce identical alias assignments — the artifact is read back, never re-derived per seed | `tests/test_model_persistence.py:510` |
| **old-cache fallback is documented, not silent** | a graph cache without a sibling artifact keeps today's pre-FSC-2 behaviour, and the lossy result is the one the test documents | `tests/test_model_persistence.py:549`, `:602` |
| **payload hygiene** | `graph_with_alias_of` never mutates the caller's graph (the served payload and the cache object) — the persisted fact stays a model-build input and never leaks into a response; `test_model_cache_roundtrip_and_version_gates` covers every guard direction | `tests/test_model_persistence.py:700`, `:735` |

**12 tests**, `backend/tests/test_model_persistence.py` (uncommitted at this update — new file in
the working tree). Suite verified green locally by this documentation pass.

---

## 11 · H11 — the 7 MERGE-column connectivity defects (Phase 4d-gc) + the G8 multi-anchor fold (LANDED)

R4-H's tightening of the R44 twin waiver handed back 14 live `column_connectivity` findings; they
were adjudicated one by one into `_ADJUDICATED_CONNECTIVITY` as 7 false positives (kept) and 7
DEFECTs (recorded for a fix). The 7 DEFECTs are the same shape: a MERGE statement's column —
walked by `_walk_merge` through the merge scope (`ON` / `UPDATE SET` / `WHEN`) — resolves I2 to
the USING/derived alias's PHYSICAL table, and R44's family-2 twin registers it under the
owner-qualified spelling `{owner}.{col}`. Its qualifier IS the physical owner, so Pass 4a skips it
(the owner is the original name), Phase 4d's prefix match misses it, and Phase 4d-gb's gate
enumerates only `GROUP BY` + the OCCURRENCE marker — the MERGE/JOIN-ON clauses fell between the
two and the variable carried **no incoming SCHEMA edge at all** (topology
`column_connectivity`: "no connection from source table").

| Row | What landed | Tree proof |
|-----|-------------|------------|
| **Phase 4d-gc** | MERGE/predicate-clause columns get their PHYSICAL owner's belongs-to SCHEMA edge. `_MERGE_COLUMN_CLAUSES` is the documented clause gate (`MERGE ON`, `MERGE UPDATE SET`, `MERGE WHEN`, `MERGE INSERT`, `JOIN ON`) and `_statement_scope` is the statement key | `backend/app/extractor/dependency_graph.py:52` (`_clause_of`), `:113-116` (`_MERGE_COLUMN_CLAUSES`), `:118` (`_statement_scope`), `:829-905` (Phase 4d-gc) |
| **the over-admission guard** | admission needs the model's OWN schema evidence that `owner` really has `col`: a QUALIFIED read (`t.amount`) that I2 resolved to `owner` in the SAME statement. That witness is owner-scoped and never owner-spelled (an `{owner}.{col}` var's own spelling proves nothing — it is the shape under adjudication), so the rule can never witness itself. This is exactly what separates the 7 defects from the adjudicated false positives of the same clause family: fin_query4's `gps_transactions.account_id` is the twin of a RENAMED USING projection (`t.source_account_id AS account_id` @8), so no alias-spelled read of `gps_transactions.account_id` exists anywhere in the statement and the belongs-to premise is false — admitting it would fabricate a schema fact | `dependency_graph.py:844-875` (the witness build + the owner-spelled exclusion), the comment at `:829-843` |
| **blast radius measured, exactly 7** | the corpus-wide probe diffs `build_dependency_graph` output with `_MERGE_COLUMN_CLAUSES` emptied vs the real gate over EVERY sample + `financial/fin_query*.sql` and asserts **exactly 7** new edges — a wider blast radius would be an undisclosed model change | `backend/tests/test_merge_connectivity.py:244-283` (`TestCorpusBlastRadius::test_exactly_the_seven_defect_edges_corpus_wide`, message: "Phase 4d-gc admitted N edges corpus-wide, expected exactly the 7 adjudicated defects"), `:286-291` (`test_clause_gate_is_the_documented_set`) |
| **waiver reconciled** | the 7 DEFECT entries are REMOVED from `test_graph_integrity.py::_ADJUDICATED_CONNECTIVITY`; the 7 FALSE POSITIVE entries stay and must KEEP firing | `backend/tests/test_graph_integrity.py:167-232` (now holds only the FALSE POSITIVE entries: fin_query4 ×1, fin_query8 ×2, fin_query14 ×4), `backend/tests/test_merge_connectivity.py:70-90` (`MERGE_DEFECTS` — the 7, each asserted to have STOPPED tripping), `:226-227` (the false positive whose waiver entry stays) |
| **35 tests** | every defect direction: the edge exists, the checker is silent, the false positives still trip, the clause gate is the documented set, the corpus blast radius is exactly 7 | `backend/tests/test_merge_connectivity.py` — **35 passed** (re-run by this documentation pass) |
| **G8 — the RC-B multi-anchor fold (the other half of this round)** | the L2 display fold (`_combine_edges`) keyed on (source, target, edge_type) and kept ONE carrier per pair, so when N occurrences of the searched field reached the same target the payload showed one anchor and the other N−1 went dark — the model carried the per-occurrence edges the whole time. Fold key is now (source, target, edge_type, ANCHOR) with ANCHOR = the `highlight_line` the carrier will be served with; K distinct anchors ⇒ K served edges, ascending | `backend/tests/test_g8_multi_anchor.py:1-21` (root cause + the SUP_M L95/L156/L163/L206 evidence), `backend/app/services/l2_builder.py` `_combine_edges` — **6 passed** |

**The witness count this round re-pinned.** RC-B's multi-anchor fold moved the flagship display
edge count 528 → 673/674, and the 673-vs-674 FLAP was a separate pre-existing cross-process leak
(determinism leak #3): for ~10 REF edges the same logical edge was minted from a DIFFERENT
duplicate raw node id depending on PYTHONHASHSEED — invisible under the single-carrier fold,
sensitive under multi-anchor. The PROVENANCE determinism fix in §12 removed the hash-order source
of most of that flap, and guard 3b dropped the 14 direct 2-cycles (7 SUP_M, 7 RFN; 5 of them
materialized as SUP_M display edges), so the count is now **stable at 668 across PYTHONHASHSEED
0–3**, with served lit-line sets and flow closures byte-identical on all 7 flagship searches.
(R46d's continuation twins moved it 668 → 669 afterwards — one new FILTER@182 row-selection edge,
SQL-text-verified.) `backend/tests/test_physical_model_equivalence.py:323-359`.

---

## 12 · X1 relay — the container-PROVENANCE bridge: deterministic, non-cyclic, and KEPT (LANDED)

Phase 3's container bridge (G7 RC-C, `EXTRACTOR_VERSION 2026-08-28.10`) wires a container body
(CTE / SUBQUERY / VIRTUAL_TABLE) that produces a value to the outside reader that consumes it —
the seam where every container chain was value-disconnected (RC-C: the whole upstream chain of
`bdm_acc_loan_info.repay_acct_no` stayed dark while its downstream reads were lit). X1 re-reviewed
the phase and found two determinism/shape defects plus a scope question.

| Row | Finding | Fix / decision | Tree proof |
|-----|---------|----------------|------------|
| **defect 1 (HIGH)** | the candidate containers live in a `set` (`_prov_bodies`), so `for body in bodies` walked them in hash-random order and `producers[-1]` inherited that order — the picked producer, and with it the served L2 edge id, FLIPPED BETWEEN PROCESSES. Measured before the fix: **7 distinct PROVENANCE pick-sets on RFN across 8 PYTHONHASHSEEDs, 2 on SUP_M** | the candidate list is built ONCE and put in a TOTAL ORDER before anything consumes it: `sorted(..., key=(line_start, var_order[id]))`. Process-independent AND the D3 last-writer-wins the comment always claimed (latest line at-or-before the read, script order breaking the tie) | `backend/app/extractor/dependency_graph.py:630-646` (X1 fix 1 + the sorted pick), `:645` (the key); `backend/tests/test_dependency_graph.py:165-215` (`TestProvenancePhase` — the two-source `d1` fixture that flips under the pre-fix pick, and `test_pick_is_identical_across_process_hash_seeds` which varies the hash in a CHILD process, the only honest way) |
| **defect 2 (MED-HIGH)** | guard 3 only saw edges INTO the reader, so an existing reader → producer REF/TRANSFORM leg coexisted with the new producer → reader PROVENANCE leg — **14 direct 2-cycles corpus-wide** (7 SUP_M, 7 RFN) | guard 3b, the reverse direction: a producer → reader leg is refused when the reader → producer leg already exists. The container's value already reaches the reader through that leg; wiring the pair backwards adds nothing but the cycle | `dependency_graph.py:663-671` (X1 fix 2), `backend/tests/test_dependency_graph.py` (`TestProvenancePhase` docstring, defects 1 and 2) |
| **the scope question — the phase is KEPT** | X1's earlier strip-measurement of the phase predated the J12-10 walker that now CONSUMES `PROVENANCE` edges, so the number it measured is no longer the number that matters: stripping the phase today loses the lit lines the walker rides (measured **47–80 lit lines per search** on the flagship searches). The phase stays | the direction is value direction (producer → reader) with operation `PROVENANCE`; `lineage` admits its forward half unconditionally and gates only the reverse half on the searched field — the value-correct direction. (X1 also corrected the in-code comment, whose "consumer to producer" was inverted relative to the stored source/target order.) A plain REFERENCE edge here would be walked BOTH ways by the strict walker and fan the container's column out to every same-named var in the script — measured 16 → 267 nodes on RFN `reserved_field9` | `backend/app/extractor/lineage.py:1203-1219` (the `read` flag + the X1 correction), `dependency_graph.py:672-682` (the direction rationale); the strip/keep figure is a working-session measurement with no repo artifact — recorded here at that confidence, as §8's provenance note does |

**Re-pin consequence:** the flagship's served display edge count is pinned at the §11 value
(stable 668, then 669 after R46d), with the witness loop re-verifying every remaining edge —
`test_physical_model_equivalence.py` asserts the count and runs the witness, so a drift fails with
the reason in the message. G7's own suite (`tests/test_g7_rc_c_fixes.py`, **17 passed**) pins the
chain-lit outcomes, the no-duplicate-feed guard, the physical-table exemption, the jaccard-seed
invariance and the two "why 637 cannot light" adjudications.

> **Not recoverable from the tree (flagged for the orchestrator):** two X1 round items have no
> code-side marker this pass could find — (a) the "anchor-rule consistency proof 0/481" (a
> measurement over 481 anchors with 0 inconsistencies, transcript-only) and (b) the "
> `_flow_memo` TypeError transient" (the caller-scoped memo's guard shape is in
> `lineage.py:897-911` and `test_perf_byte_identical.py:337-392` covers staleness/refill, but no
> tree artifact names the transient). Both are recorded here so the release gate knows they were
> claimed and are not evidenced.

---

## 13 · X1 review round — RC-C + fold review (LANDED, 3 applied + 1 kept)

| Row | Finding | Verdict / fix | Tree proof |
|-----|---------|---------------|------------|
| X1-1 | PROVENANCE producer pick is hash-order dependent (defect 1 above) | **fixed** — total order | §12 row 1 |
| X1-2 | 2-cycles on a pair the phase did not create (defect 2 above) | **fixed** — guard 3b, 14 → 0 | §12 row 2 |
| X1-3 | is the phase still worth its edges, given the pre-J12-10 strip measurement? | **KEPT** with the corrected evidence; direction corrected in `lineage.py` | §12 row 3 |
| X1-4 | the fold must not over-dedup a phase edge into an existing carrier | **verified no-over-dedup** — Phase 4d-gc appends only where no belongs-to edge exists and its blast radius is pinned at exactly 7; Phase 9 (R46d) appends LAST so the L2 line-merged pass's first-carrier-wins can never displace an existing carrier | `dependency_graph.py:844-875` + the Phase 9 admission guard (`:1395-1462` in the working tree), `test_merge_connectivity.py:256` |

---

## 14 · X2 review round — fast-open / audit / index (LANDED, 5 applied + 3 report-only)

The fast-reopen + incremental-index batch (R1.9/R1.10, v3.3.194) got a dedicated review. Five
findings were real and are fixed; three are frontend holes handed to P4 report-only.

| Row | Finding | Fix | Tree proof |
|-----|---------|-----|------------|
| **X2-a — stats gate** | `stats_seen = isinstance(rs, dict)` let the LAST script's analysis decide the gate for the WHOLE report: a corpus whose final script was an old/shapeless analysis silently flipped the report to the `tables == []` fallback — every container-resolved field (⟐/CTE) became a phantom orphan while `total_columns` stayed a partial sum, wrong in both directions and ORDER-DEPENDENT | OR-form: `stats_seen = stats_seen or isinstance(rs, dict)` — ANY script carrying `resolution_stats` arms the extractor-driven report, and the per-script ACCUMULATION still reads only scripts that actually have the key | `backend/app/services/folder_index_service.py:1058-1069` |
| **X2-b — index-run refcount** | the catching-up flag was a SET with add/discard, so the FIRST finisher cleared it while a second concurrent run was still mid-flight — the search 409 gate lifted (and P2's poller handed search back) onto a half-written index, the exact false answer the gate exists to prevent. Two runs for one workspace are reachable without malice: the creator's fast-open auto-triggers `POST /index` on a stale/never-indexed workspace, so two tabs both fire | the registry is a COUNT (`_INDEX_RUNS[ws_id] = n`), clamped at 0, never sticky; `is_index_catching_up` is `count > 0` | `folder_index_service.py:2400-2417` (the X2 comment + the count), the clamp at `:2407` |
| **X2-c — utf-8 trail reads** | `_append_record` writes `ensure_ascii=False` (raw UTF-8) but the reader left the encoding to the locale: under a C/POSIX locale the first non-ASCII detail (a Chinese table name in a search detail, a UTF-8 username) raised `UnicodeDecodeError`, which the `except Exception` swallowed into `[]` — the History panel went silently blank rather than error | the reader names `encoding="utf-8"` | `backend/app/services/audit_service.py:179-188` |
| **X2-d — meta-404** | `get_workspace` inlined `json.loads(meta_path.read_text())`, so an unreadable/corrupt meta.json (a torn write from a pre-atomic-io deploy, a full disk) became an UNHANDLED exception on every route that asks "does this workspace exist" — a 500 for the whole workspace instead of the 404 every caller already handles | reads through `read_meta`, which never raises; same answer for a missing workspace, so no caller changes | `backend/app/services/workspace_service.py:114-125` |
| **X2-e — atomic CAS consolidation** | `_write_meta_cas_locked` hand-rolled its own temp+`replace` outside the shared helper (the §7 deferred cosmetic item) — same shape, but no OSError cleanup and no named encoding, and meta carries usernames so the default-locale write was the same non-ASCII hazard the readers had | routes through `atomic_io.atomic_write_text` (unique temp + `os.replace` + best-effort temp unlink), encoding named; the M1-D3 per-writer temp is kept | `backend/app/services/workspace_service.py:205-218` |
| X2 report-only | three frontend holes in the same surface | **handed to P4 report-only** — no repo artifact names them yet; flagged for the orchestrator | — |

---

## 15 · R40.13 cross-check round 2 (G9) — after G7/G8 landed (2026-09-01)

§8's round 1 adjudicated 62 SQL lines as 36 correct-covered / 11 correct-missed / 11
wrong-missed / 4 wrong-covered and failed acceptance on ENGINE closure defects. G7 (§12) and G8
(§11) have since landed, and the same 62 lines were re-adjudicated:

| Class | Round 1 | Round 2 | Note |
|-------|---------|---------|------|
| correct-covered | 36 | **45** | the 9 wrong-missed lines G7/G8 lit |
| justified-missed | 11 (counted with correct-missed) | **12** | the naive scan cannot see what the engine legitimately excludes (the R43 partition-DDL shape, the L179/L189 `rrcdm_job_log_exec_par` routing) — now adjudicated as its own class, not lumped with correct-missed |
| wrong-missed | 11 | **1** | **L206** — adjudicated IN-PASSING as a DOCUMENTED RESIDUAL, not a defect: `ON p3.lending_ref = p1.lending_ref` (SUP_M TOP3) is a join predicate on the field's NAME, not on its VALUE; `bdm_sys_acc_loan_info` is not in the searched field's value chain (no value leg reaches it, never written, the predicate's other side is the CTE projection). The raw model DOES carry the L206 JOIN edge — the residual is the R-GATE's admission decision, not a missing fact, and it is PINNED so a later ruling starts from a failing test rather than from silence. Contrast L201 (`p2.lending_ref = p1.lending_ref`), which lights because the p2 box IS in the value chain |
| wrong-covered | 4 | **4** | **RC-A — still ledgered**, unchanged by this round |

> **Provenance note.** As in §8, the 10 case scripts, the per-line verdicts and the round-2
> adjudication live in the working-session transcript; no repo artifact records the per-line
> table. What the tree DOES record for the round's one surviving wrong-missed is the L206
> adjudication itself (`backend/tests/test_v4_walker_batch.py:519-560`,
> `test_l206_join_predicate_residual` — the served-payload pin plus the proof that the raw model
> still carries the edge), and the layer's own tests remain green
> (`frontend/src/utils/stringMatch.test.js` + the SqlPanel/FieldStoryBar suites). The 9-of-11
> flip is corroborated indirectly by the tree: G7's 17 + G8's 6 tests pin the exact SUP_M/RFN
> lines the round ledgered as wrong-missed.

---

## 16 · Ledger items that landed alongside (pointers, not re-records)

| Item | Where it is recorded | Tree proof |
|------|----------------------|------------|
| **M-T1 — TVF alias anchors** (`EXTRACTOR_VERSION .11`) | `wiki/REQUIREMENTS_TRACEABILITY.md` R52 + R37.3/R37.4 amended; `CLAUDE.md` #28 amendment | a TVF alias's I1 def-site run `[name, alias]` is never adjacent (the call's argument list sits between the function-name token and the alias), so both the statement-scoped pass and the whole-stream fallback returned 0 and the alias anchored L0 — every edge riding it highlighted nothing. Opt-in `skip_parens` on the run matcher: ONE balanced parenthesized group may stand between two run tokens, bounded by the statement range, an unterminated group FAILING the candidate (never invents a line). Only the TVF alias's def site passes it (6-tuple def_site); ordinary aliases keep the 3-tuple and are byte-unchanged. 7 flagship aliases 0 → real lines (EAST5 `f`, DL `a`, RFN `p1` + `a`). `variable_extractor_v2.py:265-283` (the changelog), `:1641-1702`/`:1936-2035` (the matcher), `backend/tests/test_m_t1_tvf_alias.py` (**23 passed**) |
| **SCR — R31.35 user-config, final state** | `wiki/REQUIREMENTS_TRACEABILITY.md` R31.35 flipped ⏳ → ✅; `CLAUDE.md` #49 status flipped | `target_deploy.sh:90-...` `build_users_env` (prints the merged JSON, sets `USERS_ENV_STATUS`/`USERS_ENV_JSON`; called BARE — a subshell would drop the status and the deploy would silently provision nothing; stdout DISCARDED because that copy carries the passwords) + `strip_allowlist_comments` (`//` full-line comments only, CR/LF/TAB removed); the post-deploy step names the provisioned EMAILS, never the passwords (§"8 · Post-deploy"); `.gitignore:43-45` + the committed `users.allowlist.json.example`; `tests/deploy/test_allowlist_logic.sh` — **36 passed, 0 failed** (re-run by this documentation pass), including the subshell-trap test |
| **R46a — `is_target` scoping** | `wiki/REQUIREMENTS_TRACEABILITY.md` R46a (already recorded) | `l2_builder.py:455` (`_scope_target_stamp`), `:543`/`:622`/`:1270`/`:1324`/`:2999` (the display boundary + the consumers it must run after), `backend/tests/test_target_scoping.py` (**31 passed**) |
| **J1 — field-involvement rule (R48)** | `wiki/REQUIREMENTS_TRACEABILITY.md` R48 (already recorded) | `l2_builder.py:2506` (`_apply_field_involvement`), `:2988` (the call site), `backend/tests/test_field_involvement_rule.py` (**12 passed**) |
| **V4/V5 walker batch (not briefed to this pass, landed in the same tree)** | `EXTRACTOR_VERSION 2026-08-28.12` — R46c value-cone admission gate, FSC-1 the J12-9 owner-agnostic seed, R46e the casing-invariant closure, R46d continuation-twin edges (arm roles + family-4 JOIN-ON AND legs + Phase 9) | `backend/tests/test_v4_walker_batch.py` (19 of 20 pass locally; the 1 failure is `ModuleNotFoundError: fastapi` in THIS documentation environment, not a tree defect — the suite imports `dataflow_service` → `filter_service` → `fastapi`), `backend/tests/test_r46d_continuation_twins.py` (**29 passed**) |
