# Code Review — J12-10 Physical Model / v3.3.152 (round 13, open issues only)

> **Reviewed:** 2026-08-12 | **Version:** VERSION `3.3.152` (3.3.151 never shipped; docs narrate "151") | **HEAD:** `a3723ff` (code) / `4b40457` (deploy shim); docker `COMMIT=5a96abf` = code, metadata-only on top — consistent.
> **Scope:** `git diff acb2dcf..HEAD` — J12-10 physical-model migration (stages 1–4), LATERAL/VALUES/UNNEST, E5, J12-15/16/17, R26–R28, E4 leftovers. 61 files, +57k lines (mostly new tests + 2 design docs).
> **Reviewer:** Codex (read-only — no source modified) via 3 sub-agents: Confucius (physical model + extractor core), Parfit (builders + frontend), Heisenberg (tests + docs).
> Round-12 wiki replaced below.

## Resolved (verified — all round-12 open items closed)

- **D2 WRITE_READ field-blind** — FIXED (`lineage.py:672-700,733-790`, commit `24a7807`): field-aware DML gates (`_dml_write_leg` + `_stmt_field_parts` + TABLE_FLOW write-leg twins). Probe: `(sup,charge_department)`=6, `(sup,lending_ref)`=6, **no rrcdm@211 leak** (was 7/7 with leak); L2 filtered 5/7, 5/7 — rrcdm absent from both. Implemented walker-side (no `read_fields` carrier — documented choice).
- **N11 unguarded int()** — FIXED: **0 bare `int(` remain in l2_builder**; all sites use `_safe_int` (`highlight_strategies.py:85`), swept in `ea15abf`.
- **C-3 cross-run stale caches** — FIXED: analysis-cache key now `md5(extractor_version + rel_path + sql_text)` with legacy-file deletion (`folder_index_service.py:408-433`); cross-run revoke re-adds to `extractor_unresolved` (:717-721).
- **Shared walkable-set contract (RC-1)** — FIXED: new `walkable_set.py` single source (`FIELD_WALKABLE`/`CONDITIONAL`/`NEVER_WALKED`/`BRIDGE_EMIT_TYPES`); `FIELD_LAND`/`NEVER` aliases; import-time partition asserts; `dependency_graph` emits only `BRIDGE_EMIT_TYPES`. Tests 13/13.
- **J12-10 physical model** — implemented, pure, read-only projection (never patched, not serialized — rebuilt per load from analysis cache/graph data). Flagship: 32 tables / 158 fields / 781 edges / 253 occurrences / 0 unparented. Proxies deleted (`_build_id_map`, `_sync_alias_and_dml_fields`, `dml_pairs`, `merged_original_ids`).
- **Stage-2 byte-identity** — VERIFIED: `test_l2_snapshot.py` 13/13 byte-equal vs committed snapshots, zero rebaseline at stage 2; later rebaselines documented (Appendix B).
- **LATERAL/VALUES/UNNEST + E5** — verified via synthetic probes + `test_unnamed_constructs.py` 15/15, `test_virtual_node_lines.py` 5/5 (⟐ VT lines, E5 fallback).
- **J12-15/16/17** — implemented + green (per-statement DML trunk, dedup `(parent_table_id,label)`, `⟐ insert` admit, id recompute on retarget).
- **R26–R28 frontend** — mech payload REMOVED (intentional, see #1), node-role legend (Source/Target/Waypoint, `L2_ROLE_COLORS`), `labelDecoration @L{line}`; vitest **122/122**.
- **Round-12 doc-staleness #8** — 3/3 fixed (Issue-1 header, sup=9 count, cache 3_2_20 narration).
- **Test suite (targeted)** — **127 passed / 0 failed** across 12 files; equivalence 12/12, walkable+D2 13, l1_physical 8, l2_stage4 5, unnamed 15, jaccard 1 (floors ≥ 1.0), flow_roles 13, l1_l2 14, dedup 6, walker_gaps 11.

## Open issues

1. **R26.3 doc stale — `mech` REMOVED but TRACEABILITY says RETAINED** (Med, doc): `wiki/REQUIREMENTS_TRACEABILITY.md:201` marks R26.3 ✅ "DELIBERATELY RETAINED… still emit"; code/snapshots/tests removed it (no `_build_mechanism`, 0 `"mech"` in snapshots, `test_mech_payload.py` pins removal, cache 3_2_24). **Fix**: update the R26.3 row to "removed in integration turn (3_2_24)".
2. **Backward-compat: `graph.edges[].data.mech` removed** (Med, by design but externally visible): the only dropped L2 key; shipped frontend no longer reads it; external consumers would break. **Fix**: document the removal in the API changelog; keep cache bump (done, 3_2_24).
3. **Full-graph `/graph` content drift unpinned** (Low-Med): `alias_map` 14→9 keys (identity self-entries dropped), `table_fields` 36→30 (7 `⟐` VT keys dropped, `ods_hub_lsacmsp` added, ~22 value-diffs); shape unchanged but no snapshot gate covers `/graph` (only L2). **Fix**: add a `/graph` snapshot or pin the projection.
4. **`cache_keys.py` docstring misses `2026-08-11.3`** (Low): extractor bumped `.1→.2→.3` (D3 round, `fe65446`); docstring stops at `.2`. **Fix**: add the `.3` entry.
5. **`jaccard_canonical.py` dl-round docstring "CANONICAL_ROWS 55" vs module 56** (Low, off-by-one). **Fix**: 55 → 56.
6. **`l1_builder.py:321-325` stale NOTE** (Low): claims graph-backed models "lose every edge" — contradicted by `physical_model.py:225-243` source/target normalization; conclusion (prefer analysis cache) still sound. **Fix**: update the comment.
7. **`_classify_compound_nodes` dereferences `entity_of_id` unconditionally** (Low): `physical_model=None` default but docstring's defensive fallback only covers a per-var miss, not a None model — safe today (only caller passes a model). **Fix**: guard `None`.
8. **S3 `_anchor_head_last` new behavior, thin direct coverage** (Low): identical statement/CTE body anchors on own occurrence; no dedicated unit test (only indirect via tpcds snapshots). **Fix**: add a unit test.
9. **Housekeeping** (Low): `screenshots/` = 60 tracked PNGs, 21 MB, not gitignored (incl. 8 new `code2-*`); `tools/e2e_test/ocr_lines_tmp.js` untracked temp. **Fix**: `.gitignore` + `git rm --cached screenshots/`; delete temp.
10. **`PHYSICAL_MODEL_STAGE2_CONTRACT.md` §8/§10.6 superseded but self-describes as live** (Low, doc): still says keep `sync_`/`dml_` proxies + `dml_pairs`; stages 3/4 deleted them (the migration map's EXECUTION sections say so, the contract doc itself doesn't). **Fix**: add a superseded-by-stages-3/4 banner.
11. **Extractor suite not fully swept** (Info): full-suite run time-boxed ~13 min (large extractor suite, no failures before timeout); targeted suites all green. **Fix**: run the full suite on the container stack (py3.11/3.12) before release.

## Priority advice (no source modified)

1. **Docs accuracy first** (#1/#4/#5/#10): 4 one-line doc fixes — cheap, prevents wrong engineering decisions (esp. R26.3 mech claim).
2. **Pin `/graph`** (#3): the only un-snapshotted surface with real content drift.
3. **API changelog** (#2): announce the `mech` removal for external consumers.
4. **Hardening** (#6/#7/#8): stale NOTE, None-model guard, S3 anchor test.
5. **Housekeeping** (#9) + full-suite run on the image stack (#11).

## Verification method

- 3 sub-agents in parallel (Confucius: physical model + extractor + D2/C-3/N11/shared-contract re-checks with live probes; Parfit: builders byte-identity + frontend + vitest 122; Heisenberg: 12 test files run live + docs/VERSION/RELEASE verification). Runtime probes on `BDM_ACC_LOAN_INFO_SUP_M.sql` (253 vars / 781 deps; model 32/158/781/253/0) + `BDM_ACC_LOAN_INFO_PL.sql` + `_Digitallending.sql` regression sanity.
- No source files modified.
