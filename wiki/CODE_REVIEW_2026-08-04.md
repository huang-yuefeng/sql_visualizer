# Code Review & Advice — SQL Data Flow Visualizer

> **Date:** 2026-08-04 | **Version:** 3.3.129 | **Reviewer:** Codex (read-only review — no source modified)
> **Scope:** `backend/app` (FastAPI + sqlglot), `frontend/src` (React + Cytoscape.js), docs, tests, repo hygiene.

---

## 1. Baseline (verified by running — nothing modified)

| Check | Result |
|-------|--------|
| Backend tests (`pytest tests/ -q`) | ✅ **339 passed / 0 failed** (3.5s) |
| Frontend unit tests (`vitest run`) | ✅ **23 passed / 2 files** |
| L1/L2 integration tests | ✅ 5 passed |
| L2 build on `multi_workflow/step3` | ✅ 8 nodes / 7 edges (pipeline runs in ~4ms) |

**Test baseline note:** `ONBOARDING.md` says "expect 334 passed, 5 skipped" — now 339/0. `CLAUDE.md` also stale (says version 3.3.106 and `dataflow_service.py` = 1989 lines; actual 3.3.129 and 445 lines).

---

## 2. Findings Summary

| ID | Finding | Priority | Type | File(s) |
|----|---------|----------|------|---------|
| H1 | Path traversal in `ws_id` → arbitrary directory deletion | P0 | Security | `workspace_service.py:62-129` |
| H2 | `target_field_sc` undefined name (latent `NameError`) | P1 | Defect (time-bomb) | `l2_builder.py:164`, `dataflow_service.py:442` |
| H3 | `source_columns` computed but dropped at graph boundary (Weakness 2 recurrence) | P1 | Data contract | `graph_service.py:138-160`, `lineage.py:132,302`, `l2_builder.py:164` |
| M1 | Literal backspace (0x08) inside regex — subquery count always 0 | P2 | Defect | `adapter.py:66` |
| M2 | L2 never uses index-time precomputed graph cache (key mismatch) | P2 | Performance / cache | `folder_index_service.py:94`, `l2_builder.py:92`, `dataflow_service.py:278`, `multi_script_service.py` |
| M3 | Two-file filter = union; requirement (R19) is intersection — not implemented, no tests | P2 | Requirement gap | `workspace.py:157-210` |
| M4 | `_build_l1_graph` top-level `except` returns degraded graph as success | P2 | Error handling | `l1_builder.py:868-877` |
| M5 | Duplicated category/style definitions remain (Weakness 1 partial) | P3 | Code smell | `dataflow_service.py:378-441`, `graph_service.py:105-126`, `graphStyles.js` |
| L1 | `DELETE /api/workspace` wipes ALL workspaces, no guard/auth | P2 | Security | `workspace.py:275` |
| L2 | Orphaned SSE queues never cleaned by 24h auto-cleanup | P3 | Memory leak (slow) | `logger.py:_log_queues` |
| L3 | `_INDEX_PROGRESS` module dict — no lock; `errors` never surfaced | P3 | Concurrency | `folder_index_service.py` |
| L4 | `adapter.py` sys.path insert of non-existent `sql_field_extractor` | P3 | Dead code | `adapter.py:16-19` |
| L5 | Legacy type `"window_computed"` — extractor produces `window` | P3 | Code smell | `graph_service.py:138` |
| L6 | ~170MB build artifacts tracked in git (tarball, docker_image parts, static.bak.*, .bak files) | P3 | Repo hygiene | repo root |
| L7 | Silent error swallowing still pervasive (29 `except Exception` backend, 23 `catch` frontend) | P3 | Systemic | `backend/app`, `frontend/src` |

---

## 3. Detailed Findings

### H1 — Path traversal in `ws_id` → arbitrary directory deletion (P0, Security)

`get_workspace`, `get_workspace_dir`, `delete_workspace` build paths as `WORKSPACE_ROOT / ws_id` with **no validation** of `ws_id`.

Verified:
```python
Path('/tmp/workspaces') / '..'  # → resolves to /tmp
delete_workspace('..')          # → shutil.rmtree('/tmp')  ← catastrophic
delete_workspace('.')           # → rmtree('/tmp/workspaces') ← wipes all workspaces
```

The API binds `0.0.0.0:8000`, has `CORS: *`, and **no authentication**. `{ws_id}` matches `..`, so a raw client (`curl --path-as-is .../api/workspace/.. -X DELETE`) would delete `/tmp`. The zip-extraction path already guards traversal correctly — the `ws_id` side does not.

**Fix:** validate `ws_id` at the router boundary or in `workspace_service`, e.g.:
```python
import re
if not re.fullmatch(r'[0-9a-f]{12}', ws_id):
    raise HTTPException(400, "Invalid workspace id")
```

---

### H2 — `target_field_sc` undefined name — latent `NameError` (P1)

`l2_builder.py:164` calls `target_field_sc(sc, target_field)`, but the function is defined **only** in `dataflow_service.py:442` and is **never imported** into `l2_builder.py` (importing it would be circular, since `dataflow_service` imports `l2_builder`).

Today this is dead code: the loop reads `nd.get("source_columns", [])`, and `build_graph_data` never puts `source_columns` on nodes, so the branch never executes. **If anyone adds `source_columns` to graph nodes — which the code clearly intends — L2 builds crash with `NameError`.**

**Fix:** define the helper locally in `l2_builder.py` (or move to a shared module) and/or delete the dead branch.

---

### H3 — `source_columns` computed but dropped at graph boundary (P1, Weakness 2 recurrence)

The extractor *does* produce `source_columns` (verified: `so.order_id → ['so.order_id']` in raw analysis JSON), but `build_graph_data` (`graph_service.py:138-160`) does not copy it into node data. Three downstream consumers read `nd.get("source_columns", [])` and silently get `[]`:

| Consumer | Line | Effect |
|----------|------|--------|
| `l2_builder.py` target-node detection | 164 | source-column matching silently never works |
| `lineage.py` seed matching src_cols branch | 132 | dead |
| `lineage.py` `filter_relevant` fallback | 302 | dead |

This is exactly the "information computed but not carried" pattern that caused Bugs 41/43/45/48.

**Fix:** either carry `source_columns` through `build_graph_data` (add to the versioned cache contract) or delete all three dead branches, plus a test asserting the intended behavior.

---

### M1 — Literal backspace (0x08) inside regex (P2)

`adapter.py:66`:
```python
subq_count = len(re.findall(r'\(\s*SELECT<0x08>', sql_text, re.IGNORECASE))
```
Confirmed with `cat -A` (`^H`). The pattern can never match → **subquery count in every pipeline profile is always 0**. Line 53 uses `\b` correctly — this one lost the backslash. One-character fix (`\b`).

---

### M2 — L2 never uses the index-time precomputed graph cache (P2)

- Indexing writes `cache/graph_{key}.json` (`folder_index_service.py:94`)
- L2 reads/writes `cache/graph_3_2_15_{key}.json` (`l2_builder.py:92`, `dataflow_service.py:278`)

Different namespaces → L2 re-parses/re-extracts every script on first open; `precomputed_count` is misleading. Additionally, every L1 search re-analyzes all scripts via `analyze_multiple_scripts` (no cache read) even though graph caches exist. Fine at 5 scripts (~4ms), a hot path at hundreds.

**Fix:** unify the cache key (drop hardcoded `3_2_15_` prefix or make it version-driven) and have L1/L2 read precomputed graphs.

---

### M3 — Two-file filter union vs intersection (R19) not implemented (P2)

Verified `workspace.py:157-210`: File 2 does `allowed_tables.add(tn)` → union A∪B, with only a diagnostic warning. The documented R19 design (intersection A∩B, column restriction to effective tables, TC1–TC10 in `BUG_ANALYSIS_AND_SUGGESTIONS.md`) is pending; `test_filter_config.py` does not exist yet.

---

### M4 — `_build_l1_graph` degraded fallback (P2)

`l1_builder.py:868-877`: top-level `except Exception` prints a traceback but returns a bare script-node graph **as success** — the UI shows a "broken" graph with no error signal. Recommend returning `{"error": ...}` to the client.

---

### M5 — Duplicated definitions remain (P3, Weakness 1 partial)

`dataflow_service.py:378-441` still re-defines `CATEGORY_MAP`, `_get_edge_style`, `_get_category`, `_get_category_color` duplicating `graph_service.py:105-126` (only `EDGE_TYPE_STYLE`/`EDGE_TYPE_ORDER` were deduped). Frontend `CATEGORY_EDGE_STYLES` (`graphStyles.js`) independently re-encodes the same edge colors as backend `EDGE_TYPE_STYLE` — two color systems for one concept.

---

### L1–L7 — Low priority items

- **L1** `DELETE /api/workspace` (workspace.py:275) wipes all workspaces, no confirmation/guard.
- **L2** `logger.py:_log_queues` grows per-workspace; removed only on explicit delete, not on 24h auto-cleanup (per-queue bounded at 500, dict unbounded).
- **L3** `_INDEX_PROGRESS` — module dict, no lock; concurrent index requests interleave; `errors` always reset to `[]`.
- **L4** `adapter.py:16-19` inserts a `sql_field_extractor` path 5 dirs above the repo that does not exist.
- **L5** `graph_service.py:138` checks `"window_computed"`; extractor produces `window` — window/case/expression nodes skip `table_name`/`field_name` resolution.
- **L6** Git-tracked build artifacts: `sql_visualizer_v3.3.72.tar.gz` (79MB), `docker_image/part_00`+`part_01` (82MB), multiple `backend/app/static.bak.*` dirs, `.bak` sources, `eng.traineddata` (5MB). Recommend `git rm --cached` + `.gitignore`.
- **L7** 29 `except Exception` in backend, 23 `catch (e) { console.error }` in frontend; `api.autocomplete()` remains dead code (Bug 49).

---

## 4. Recommended Action Order

| # | Action | Priority | Effort |
|---|--------|----------|--------|
| 1 | Validate `ws_id` (H1) — one-liner, catastrophic downside | P0 | S |
| 2 | Decide `source_columns` contract; fix `target_field_sc` (H2+H3) | P1 | S–M |
| 3 | Fix backspace regex `\b` (M1) | P2 | XS |
| 4 | Unify graph cache keys, reuse precomputed graphs (M2) | P2 | M |
| 5 | Implement R19 intersection + `test_filter_config.py` (M3) | P2 | M |
| 6 | Add full-HTTP journey test (CW10, still open) | P2 | M |
| 7 | Finish dedup of CATEGORY_MAP/helpers + frontend colors (M5) | P3 | S–M |

---

## 5. What's Working Well (keep it)

- Single-source `EDGE_SEMANTICS` table in `lineage.py`; `PRODUCTION_EDGES` shared with L1.
- P4/P5 pre-resolved `alias_map`/`table_fields` in the cache contract; `format_version` guard.
- Diagnostic ASCII blocks (R15–R17) make filter/search state visible.
- Disciplined "each fix leaves a test" pattern (`test_l1_l2_integration.py`).
- Layout constants centralized in `config/layout.js` (single source of truth honored).
- Zip extraction already guards path traversal (the `ws_id` side should match it).

---

## 6. Open Follow-ups (per project convention)

- Record these findings in `tools/BUG_ANALYSIS_AND_SUGGESTIONS.md` (e.g. CW11/CW12 or new bug entries) before implementing.
- Update stale docs: `CLAUDE.md` (version, dataflow_service.py line count), `ONBOARDING.md` (test counts).
