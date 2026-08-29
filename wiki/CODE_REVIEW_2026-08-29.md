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
used.

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
