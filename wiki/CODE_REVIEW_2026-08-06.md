# Code Review & Advice — SQL Data Flow Visualizer

> **Date:** 2026-08-06 | **Version:** 3.3.132 (HEAD `ee03714`) | **Reviewer:** Codex (read-only review — no source modified)
> **Scope:** today's commits `e47f4a3..HEAD` — `6636485` (graph E1), `b3409b6` (design), `c919471` (residual-orphan fixes 1c/2a/2b), `bc07592` (filter_service extraction, L2/L3, frontend R2/R20), `ee03714` (S4 Phase 0/1 instrumentation).
> **Delta:** 41 files, +3,651 / −876. Backend `backend/app/extractor`, `backend/app/services`, `backend/app/routers`; frontend `frontend/src`; tests; docs.

---

## 1. Baseline

| Check | Result |
|-------|--------|
| Commits reviewed | 5 (see header) — full `git diff e47f4a3..HEAD` per file |
| Backend tests | ✅ **427 runnable tests pass** (sub-agent rerun; `test_filter_config.py` requires `starlette` — not installed in review env). Commit messages report full suite 445 passed / 5 skipped. |
| Frontend util tests | ✅ `resolutionReport.test.js` — 8 meaningful cases (both index/extractor shapes, division-by-zero, backend fallback, null/absent inputs) |
| F6 extraction fidelity | ✅ Byte-for-byte faithful except the intentional R1 feature (verified hunk-by-hunk against `bc07592~1`) |
| Old-cache byte-identity (S4b) | ✅ Genuine — no new keys ⇒ `s4c_seen=False`, report block unchanged, summary zero-shaped |

**Test baseline note:** the frontend's riskiest new logic (async restore effect, `ResolutionReport` component, `FilterPanel` banner) has **zero component tests** — the defects in M8/M9/M10 live exactly there.

---

## 2. Findings Summary

| ID | Finding | Priority | Type | File(s) |
|----|---------|----------|------|---------|
| H1 | `resolve_script` path traversal → arbitrary file read (CSV `SCRIPT_NAME` reachable) | P0 | Security | `services/filter_service.py:23-46, 350-371` |
| M2 | Fix B (S1 bare-column alias chain) mis-attributes alias when a CTE is in scope | P1 | Defect (data correctness) | `extractor/variable_extractor_v2.py:1183-1198` |
| M3 | S4 evidence canonicalization holes — case-sensitive CTE/derived guards + MERGE target alias → phantom schema evidence | P1 | Defect (audit correctness) | `extractor/variable_extractor_v2.py:1025-1050, _walk_merge` |
| M4 | Fix A (set-op-in-subquery) double-counts `total_columns` (phantom copies) — coverage numbers inflated, not release-comparable | P2 | Defect (metrics) | `extractor/variable_extractor_v2.py:845-867` |
| M5 | Malformed CSV (short row) → `None.strip()` → unhandled 500 | P2 | Robustness | `services/filter_service.py:104-105, 136-137` |
| M6 | R1 breaks `filtered_fi` ↔ `filtered_ti` symmetry for fields shared by constrained/unconstrained tables | P2 | Defect (data contract) | `services/filter_service.py:213-236` |
| M7 | L2 SSE queue auto-cleanup defeated by `_push` recreate-on-miss | P2 | Memory growth | `services/logger.py:27-36, 62-75` |
| M8 | R3 no-match banner disappears after reload (server persists view without `match_mode`/`message`) | P2 | Defect (UX) | `frontend/src/DataFlowApp.jsx:186-190, 586` |
| M9 | ResolutionReport "No unresolved columns" keyed on names presence, not `unresolvedCount` | P2 | Defect (display) | `frontend/src/components/ResolutionReport.jsx:52-64` |
| M10 | Coverage badge can show "100.0%" next to "N unresolved" (zero-total old caches) | P2 | Defect (display) | `frontend/src/utils/resolutionReport.js:70-73`, `services/folder_index_service.py:442` |
| M11 | `schema_candidates_summary` (new API field + SSE audit) has no frontend consumer | P3 | Contract gap | `services/folder_index_service.py:478-483`, `frontend/src` |
| L1-L15 | See §3.3 (owner-not-indexed, case-fold merges tables, Fix C shadow, junk record names, two-hop miss, graph sentinel policy, shallow copy, TOCTOU read, blocking IO, CSV size/encoding, client.js error body, dark card, dead code, nowrap, view shape) | P3 | Various | see §3.3 |
| N1-N7 | Nits (§3.4): dedup-key docstring, box overflow, partial-key `s4c_seen`, dead `_diag_box`/`W`, R1 mixed-row note, ref-count edge, screenshots + 84MB docker blobs in git | P3 | Nits / hygiene | see §3.4 |

---

## 3. Detailed Findings

### H1 — Path traversal in `resolve_script` → arbitrary file read (P0, Security)

`services/filter_service.py:23-46`:

```python
def resolve_script(ws_id: str, name: str) -> Path | None:
    if not name:
        return None
    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    cands = [name]
    if not name.lower().endswith(".sql"):
        cands.append(name + ".sql")
    for c in list(cands):
        cands.append(os.path.basename(c))
    for c in cands:
        p = scripts_dir / c          # ← no containment check
        if p.exists():
            return p
    ...
```

`name` is fully user-controlled: the SQL-evidence diagnostic loop takes `SCRIPT_NAME` values from an uploaded CSV (`:356-357`), calls `resolve_script(ws_id, cname)` (`:366`), then reads the file and logs every line containing the chosen table-name substring (`:369-371`).

Verified escapes (pathlib semantics):
```python
>>> Path("/ws/<id>/scripts") / "/etc/passwd"          # absolute right operand
PosixPath('/etc/passwd')                               # replaces the base
>>> Path("/ws/<id>/scripts") / "../../../etc/passwd"   # .. chain
PosixPath('/ws/<id>/scripts/../../../etc/passwd')      # resolves to /etc/passwd
```

`.exists()` passes for both. This is a line-oriented arbitrary-file-read primitive (pick a table name matching a line of the target file). It pre-existed as a dormant closure in `workspace.py`, but R5 promoted it to a shared service used by a second caller (`folder_index_service`'s `_resolve_orphan_script`) — fix it at the shared helper now.

**Fix:** resolve and verify containment in both the candidate loop and the rglob fallback:
```python
scripts_root = scripts_dir.resolve()
for c in cands:
    p = (scripts_dir / c).resolve()
    if p.is_relative_to(scripts_root) and p.exists():
        return p
```
(or reuse `workspace_service.get_script_path`, which already does `resolve()` + prefix check).

---

### M2 — Fix B (S1 bare-column alias chain) mis-attributes in CTE scopes (P1)

`extractor/variable_extractor_v2.py:1183-1198`:

```python
elif alias != _clean(inner.name or "") and scope is not None:
    # S1 (Fix B): alias of a plain BARE column
    distinct = self._distinct_scope_tables(scope)      # ← physical tables ONLY
    if len(distinct) == 1:
        _db, _name = distinct[0]
        ...
        attr_strategy, attr_table = "plain_alias", _name
```

The new branch re-derives attribution with `_distinct_scope_tables` (physical tables only), but the source column itself is resolved by the full S2 → Fix C → S3 chain in `_register_column`. These can disagree. Verified:

```sql
WITH w AS (SELECT id FROM t2) SELECT id AS c FROM t1, w
```
produces `c → t1` (Fix B) while its own source column `id → w` (S2 CTE). The alias and its source column end up on different tables; the graph draws `c` flowing from `t1` and `id` from `w`, and `resolved_by` miscounts the strategy.

**Fix:** don't re-derive S3 in `_walk_select_expression`. Resolve the inner bare column with the same order as `_register_column` (CTE → derived → S3), or look up the already-registered source-column var in the same context and copy its `source_tables`/strategy. At minimum run the CTE/derived checks before the S3 fallback.

---

### M3 — S4 evidence canonicalization holes → phantom schema evidence (P1)

`extractor/variable_extractor_v2.py:1025-1050`:

```python
if scope is not None:
    if table in scope.ctes or table in scope.deriveds:     # ← case-SENSITIVE
        return
    if not self._in_scope_owner(col, scope):
        return
canonical = self._resolve_alias(table, scope)
col_name = _clean(col.name or "")
if (not col_name or canonical.startswith("⟐")
        or canonical in self._cte_names                     # ← case-SENSITIVE
        or canonical in self._derived_aliases):             # ← case-SENSITIVE
    return
self._script_schemas.setdefault(canonical, set()).add(col_name)
```

**(a) Case sensitivity.** Verified: `WITH c AS (SELECT 1 AS x) SELECT C.x FROM c` records `script_schemas = {"C": ["x"]}` — a phantom table `C`. The index's S4b re-test matches case-insensitively (`m_ws_lower`), so a real table whose name case-folds to `c` can be shown as the unique owner of `x` purely from phantom evidence.

**(b) MERGE target alias.** `_walk_merge` registers the target alias as a `MERGE_TARGET` variable but never puts it in `_table_aliases`, and the ON/WHEN clause walks pass `scope=None`. So `MERGE INTO customers tgt USING orders src ON tgt.id = src.id ...` records evidence under the alias `tgt` (`{"tgt": ["id"], "orders": ["id"], "customers": ["total"]}`) — alias → physical canonicalization fails for the target side.

**Fix:** lowercase all CTE/derived membership guards (compare `field.lower()`/`canonical.lower()`), and register MERGE target/using aliases into `_table_aliases` (or pass a scope into the MERGE ON/WHEN walks).

---

### M4 — Fix A double-counts `total_columns` (P2)

`extractor/variable_extractor_v2.py:845-867`:

```python
for node in expr.walk(prune=lambda n: isinstance(n, (exp.CTE,))):
    if isinstance(node, exp.Column):
        self._register_column(node, context, defined_in, scope)   # ← branch column again
    elif isinstance(node, exp.Subquery):
        if isinstance(node.this, exp.Select):
            ...
        elif isinstance(node.this, (exp.Union, exp.Intersect, exp.Except)):
            self._subq_counter += 1
            self._walk_setop(...)     # ← NEW: branch-scoped registrations
```

`expr.walk()` still visits every `Column` in the set-op body, so branch columns register **twice**: once as an unattributed outer-context phantom copy, once via `_walk_setop` with proper branch scopes. Verified on the spider pattern: `total_columns = 6` for 4 logical columns. `coverage_pct` is derived from `total_columns`, so the headline number is inflated and not comparable with the pre-change sweep (95.8% → "96.6%"). The orphan list itself stays correct (unresolved is name-level).

**Fix:** prune set-op subquery bodies from the outer raw walk (skip descending into a `Subquery` whose body is a set-op), or document `total_columns` as var-count rather than unique-column-count.

---

### M5 — Malformed CSV → unhandled 500 (P2)

`services/filter_service.py:104-105, 136-137`:

```python
for row in rows:
    sn = row.get("SCRIPT_NAME", "").strip()    # missing trailing field → None
    tn = row.get("TABLE_NAME", "").strip()
```

`csv.DictReader` maps a short row's missing trailing fields to `None`, not `""`:
```python
>>> list(csv.DictReader(io.StringIO("SCRIPT_NAME,TABLE_NAME\nfoo")))
[{'SCRIPT_NAME': 'foo', 'TABLE_NAME': None}]
>>> row.get("TABLE_NAME", "").strip()   # AttributeError → FastAPI 500
```

Both files and the diagnostic loop at `:356` are affected.

**Fix:** `(row.get("TABLE_NAME") or "").strip()` everywhere; wrap parsing in `try/except` → `HTTPException(400, reason)`.

---

### M6 — R1 breaks `filtered_fi` ↔ `filtered_ti` symmetry (P2)

`services/filter_service.py:213-236`:

```python
# table_index pass: table KEEPS a field only if ...
filtered_fields = [f for f in tdata.get("fields", [])
                   if allowed_columns is None or f in allowed_columns or tname in unconstrained_tables]

# field_index pass: a field PASSES if it belongs to ANY unconstrained table
if allowed_columns is not None and fname not in allowed_columns \
        and not (set(fdata.get("tables", [])) & unconstrained_tables):
    continue
filtered_tables = [t for t in fdata.get("tables", [])
                   if allowed_tables is None or t in allowed_tables]   # ← lists C too
```

Scenario: field `f` is shared by unconstrained table `U` and constrained table `C` (both allowed). In `filtered_fi`, `f` passes via `U`, and `filtered_tables` lists every allowed table → `[C, U]`. But `filtered_ti["C"]["fields"]` excludes `f`. Result: `filtered_fi[f]["tables"]` claims `C` contains `f` while `filtered_ti` omits it. Old code was symmetric; R1 breaks it. Any field→table consumer reports wrong data.

**Fix:** apply the same per-table pass predicate in `filtered_tables`:
```python
filtered_tables = [t for t in fdata.get("tables", [])
                   if t in allowed_tables
                   and (allowed_columns is None or fname in allowed_columns
                        or t in unconstrained_tables)]
```

---

### M7 — L2 SSE queue auto-cleanup defeated by `_push` recreate-on-miss (P2)

`services/logger.py:27-36` vs `62-75`:

```python
def _push(ws_id, stage, message):
    if ws_id:
        q = ensure_queue(ws_id)      # ← CREATE if missing, "never drop messages"
        ...

def unregister_queue(ws_id):
    with _log_lock:
        remaining = _log_refs.get(ws_id, 0) - 1
        if remaining > 0:
            _log_refs[ws_id] = remaining
        else:
            _log_refs.pop(ws_id, None)
            _log_queues.pop(ws_id, None)   # ← queue removed here
```

After the last SSE client disconnects, `unregister_queue` pops the queue — but the next background `_push` (index run, search diagnostic, R16/R17) calls `ensure_queue`, recreating it with nobody listening and no future unregister. The registry grows forever — the exact stale-growth L2 set out to fix, just deferred. Locking is fine; the semantics are the problem.

**Fix:** in `_push`, put only when a queue already exists (lock-guarded peek; drop when nobody is listening), or keep a short tombstone so `ensure_queue` doesn't resurrect a just-removed queue.

---

### M8 — R3 no-match banner disappears after reload (P2, UX)

`frontend/src/DataFlowApp.jsx:186-190`:

```jsx
// comment: "the saved view wins when the backend hasn't persisted it
//          (F1 no_matches path skips views.json)"
const exists = restoredViews.some(v => v.view_id === savedViewId);
if (!exists) restoredViews = [...restoredViews, saved.view];
```

and `:586`:

```jsx
{graphData && activeView?.match_mode === 'no_matches' && (
  <div className="no-match-banner">⚠️ No matches: {activeView.message || 'no tables in scope'} …</div>
)}
```

The same day's backend change made the no_matches path **persist** the view via `_persist_search_view` — but without `match_mode`/`message`. After reload, `listViews` returns the server entry with the same `view_id` ⇒ `exists === true` ⇒ the localStorage copy (which carries the banner metadata) is discarded ⇒ `activeView.match_mode` is `undefined` ⇒ the banner never renders. The empty graph still restores, so the user sees a blank canvas with no explanation — the exact R3 case this feature was built for works only within the session.

**Fix:** overlay the saved metadata onto the server entry:
```jsx
if (exists) restoredViews = restoredViews.map(v =>
  v.view_id === savedViewId ? { ...v,
    match_mode: v.match_mode ?? saved.view.match_mode,
    message: v.message ?? saved.view.message } : v);
```
(or persist `match_mode`/`message` in `_persist_search_view`).

---

### M9 — ResolutionReport "No unresolved columns" keyed on names presence (P2, display)

`frontend/src/components/ResolutionReport.jsx:52-64`:

```jsx
const names = s.names && s.names.length > 0 ? s.names : null;
...
{names ? (
  <div className="rr-unresolved">Unresolved columns ({names.length})…</div>
) : (
  <div className="rr-clean">No unresolved columns</div>   // ← wrong when names missing
)}
```

`resolutionReport.js` documents that names "ride along" and may be missing. If the backend returns `resolution_stats` without `orphan_field_samples`, `names` is `null` → "No unresolved columns" renders directly under a line reporting `N unresolved`. Latent today (backend always sends samples) but contradicts the util's documented degrade-gracefully contract.

**Fix:** branch on the count: `unresolvedCount === 0 → clean`; else if `names` → list; else → "N unresolved (details unavailable)".

---

### M10 — Coverage badge can show "100.0%" with unresolved (P2, display)

`frontend/src/utils/resolutionReport.js:70-73`:

```js
let coveragePct = null;
if (total !== null && total > 0 && unresolvedCount !== null) {
  coveragePct = Math.round((1 - unresolvedCount / total) * 1000) / 10;
} else if (typeof stats.coverage_pct === 'number') {
  coveragePct = stats.coverage_pct;      // ← inherits backend 100.0 for zero total
}
```

Backend (`services/folder_index_service.py:442`) emits `coverage_pct = 100.0` when `total_cols == 0`. For old/mid-flight caches, `total` accumulates to 0 while `unresolved` can still be > 0; the frontend inherits 100.0 and renders a green "100.0%" badge next to "N unresolved (100% coverage)". `test_orphan_resolution_index.py::test_tc5_old_analysis_without_resolution_stats` pins the backend 100.0, so the fix belongs on the display side.

**Fix:** when `total === 0 && unresolvedCount > 0`, prefer `null` → "—" instead of inheriting `coverage_pct`.

---

### M11 — `schema_candidates_summary` has no frontend consumer (P3, contract gap)

`services/folder_index_service.py:478-483` adds `schema_candidates_summary` to the index response; the S4b owner-line audit goes to SSE. `grep schema_candidates_summary frontend/src` → nothing. The R20 `ResolutionReport` badge shows only coverage/by-strategy/unresolved names; the S4 audit reaches users only through the log panel. If "report-only audit" is intended, document it — as-is the commit message's "schema-candidates summary display" is not reflected in the UI.

**Fix:** render a "schema candidates" line in `ResolutionReport` when `s4c_seen`, or document the field as log-only.

---

## 3.3 Low severity (condensed)

| ID | Finding | File |
|----|---------|------|
| L1 | S4b unique-owner re-test does not require `tbl in table_index` (Phase-2 S4 does) — owner line can name an unindexed table | `folder_index_service.py:423-424` |
| L2 | `m_ws_lower`/`visible` case-folding merges distinct tables `Orders`/`orders` → false "unique" owners | `folder_index_service.py:406, 414-421` |
| L3 | Fix C "one visible derived table" runs before S3 and can shadow a physical table that also owns the column (departs from "never guess"; verified) — needs a design note or guard | `variable_extractor_v2.py:956-965` |
| L4 | Fix C records junk output names for `SELECT *` / literals (`record_name = "*"`, `"1"`) — pollutes `_derived_output_columns` | `variable_extractor_v2.py:1203-1216` |
| L5 | Two-hop missed for unaliased qualified projections (`SELECT col FROM (SELECT t.col FROM t2 t) d` stays one-hop) — missed optimization, not a bug | `variable_extractor_v2.py:1209-1214` |
| L6 | `graph_service` sentinel skip (`⟐system`/`⟐pseudo` only) is narrower than the folder index's; CTE/derived aliases can attach and collide with real table names downstream | `graph_service.py:150-155` |
| L7 | `get_index_progress` returns `dict(entry)` — nested `errors` list shared; callers can mutate shared state | `folder_index_service.py:28-34` |
| L8 | `_search_diagnostic_values` re-reads `filtered_index.json` (TOCTOU + double IO) instead of using values `_load_index` already computed | `routers/dataflow.py:63-98` |
| L9 | Blocking file IO on the async event loop (filter upload, `_persist_search_view`) — large workspaces stall the server | `filter_service.py`, `routers/dataflow.py:135` |
| L10 | No size cap on filter CSVs (zip path caps at 100 MB; these don't) → OOM/500 | `filter_service.py:87, 131` |
| L11 | UTF-8-only decode (`errors="replace"`) silently corrupts Shift-JIS/BOM files → filters match nothing with no hint | `filter_service.py:87, 131` |
| L12 | `client.js` `res.json()` throws SyntaxError on non-JSON error bodies, masking the real status | `frontend/src/api/client.js:65-68` |
| L13 | `.resolution-report` hardcodes a dark card (`#16162a`) — clashes with the supported light theme | `frontend/src/styles/app.css:455-490` |
| L14 | `MAX_NAMES` truncation branch is dead code (backend caps samples at 20); header shows 20 not the true count | `ResolutionReport.jsx:11, 57-60`, `folder_index_service.py:475` |
| L15 | `.no-match-banner` `white-space: nowrap` can overflow on long backend messages | `app.css:445-452` |

## 3.4 Nits / hygiene

- **N1** `_stash_schema_candidate` dedup key `(col_name, tuple(visible))` also collapses different statements with identical visible sets; docstring overstates scope, and `loc` is the first token match in the whole script (`variable_extractor_v2.py:1062-1065`).
- **N2** Owner lines truncate `fname`/`owner`/`script` but not `vis_txt` — a 6-table list overflows the 80-char box (`folder_index_service.py:568-575`).
- **N3** `s4c_seen` set when *any* of the three keys is present; a partially-upgraded cache prints a zero summary line — use an all-three-keys check (`folder_index_service.py:171-176`).
- **N4** no_matches persisted view shape differs from regular views (no `l1_graph_cache.target`) — keep uniform `{"nodes": [], "edges": [], "target": "table.field"}` (`routers/dataflow.py:142`).
- **N5** Dead code carried over: `_diag_box` and `W` unused in `filter_service.py:60-66`.
- **N6** R1 blank-row-wins for mixed rows silently unconstrains a table — add a one-line diagnostic (`filter_service.py:141-145`).
- **N7** Repo hygiene: 4 screenshots committed to repo root (one with typo `parse_filer_error.png`), `docker_image/part_00|01` binary blobs (~84 MB) tracked in git, `.bak`/`static.bak.*` legacy files present. Consider `.gitignore`.

---

## 4. Verified fine (no action needed)

- **F6 extraction is faithful.** The move `workspace.py` → `filter_service.py` is byte-for-byte except the intentional R1 feature (verified hunk-by-hunk); F2 `is not None` empty-set guards, Bug51/R19 intersection, `empty_intersection` override, F4 payload fields/warnings, clear-filter early return, F5 case-mismatch hint, SSE `push` stages, and the `/filter-config` response shape are all unchanged — old clients are safe.
- **`_UPDATE_SET_NODES` version-robustness is real.** sqlglot 30.8 parses UPDATE/MERGE SET items as `exp.EQ`; `UpdateSet` doesn't exist, `SetItem` does. `action = when.this or when.args.get("then")` works on 30.8.
- **Fix C semantics** (one-hop/two-hop, `len(derived_matches) == 1` ambiguity guard, walk ordering, alias reuse across statements) all check out.
- **S4b old-cache byte-identity** is genuine; defensive `isinstance` reads are correct; `schema_candidates_summary` zero-shaped on old data.
- **L3 index-progress lock** fixes torn read/write and error-wipe; the `total`/`total_columns` shadowing fix is correct.
- **`_resolve_orphan_script` → `resolve_script`** is a faithful move of the old resolver.
- Backend tests are strong and behavior-focused; no flakiness; each test owns its workspace via fixtures with `delete_workspace` teardown.

---

## 5. Test coverage gaps (add before Phase-2 auto-resolution)

- Fix B × CTE interplay (M2) — `test_fix_b_*` covers only single-table and 2-table physical scopes.
- Case-variant CTE/derived qualifier evidence (M3a) and MERGE-alias evidence (M3b).
- Fix A `total_columns` denominator (M4) — spider test asserts resolution but not the count.
- Qualified-unaliased two-hop (L5) and derived-shadowing-a-physical-table (L3).
- No end-to-end test drives `index_scripts` with *real* extractor `schema_candidates` output through the S4b block (`test_s4_report.py` monkeypatches at index level).
- Frontend: R3 restore effect / view-merge (M8), ResolutionReport empty-state and coverage branches (M9/M10), FilterPanel banner — zero component tests (`@testing-library/react` is already a devDependency but unused).

---

## 6. Key takeaways & recommended action order

1. **H1 (P0, security)** — fix the shared `resolve_script` containment check first; it is CSV-reachable and shared by two callers.
2. **M2 + M3 (P1, correctness)** — wrong real attributions (Fix B × CTE) and wrong S4b audit owners (phantom evidence). Fix + regression tests before enabling Phase-2 auto-resolution.
3. **M4 (P2, metrics)** — decide: suppress phantom counting for set-op bodies or document `total_columns` as var-count; stop quoting coverage numbers as release-comparable.
4. **M8/M9/M10 (P2, frontend)** — small display/logic fixes + component tests; the defects sit exactly in the untested branches.
5. **M5-M7, M11 (P2/P3)** — CSV hardening (short rows → 400, size cap, encoding), queue-cleanup semantics, and the S4 summary UI contract.
6. **Backend test quality is a strong point this day** — protect it by adding the M2/M3/M4 regression tests listed in §5.
