"""Folder index service — scan directory tree, build table/field indexes."""
import json
import threading
from pathlib import Path
from app.services.workspace_service import get_workspace_dir, get_script_path
from app.services.logger import _push
from app.services.filter_service import resolve_script

SQL_EXTENSIONS = {".sql"}


# Progress tracking for polling
_INDEX_PROGRESS = {}  # ws_id -> {current, total, phase, errors}
# L3: concurrent index runs / pollers must not tear the progress dict.
_INDEX_PROGRESS_LOCK = threading.Lock()

def _set_progress(ws_id: str, current: int, total: int, phase: str, errors=None):
    """Update index progress. `errors=None` preserves already-recorded
    errors (L3 — the error path must not silently reset them)."""
    with _INDEX_PROGRESS_LOCK:
        prev = _INDEX_PROGRESS.get(ws_id)
        if errors is None:
            errors = prev.get("errors", []) if prev else []
        _INDEX_PROGRESS[ws_id] = {"current": current, "total": total,
                                  "phase": phase, "errors": errors}

def get_index_progress(ws_id: str) -> dict:
    """Return a snapshot of the progress dict (callers may not mutate it)."""
    with _INDEX_PROGRESS_LOCK:
        entry = _INDEX_PROGRESS.get(ws_id)
    if entry is None:
        return {"current": 0, "total": 0, "phase": "idle", "errors": []}
    # L7 (review): a shallow dict(entry) shares the nested `errors` list —
    # a caller mutating the returned list would corrupt the registry. Copy.
    return {"current": entry.get("current", 0),
            "total": entry.get("total", 0),
            "phase": entry.get("phase", ""),
            "errors": list(entry.get("errors", []))}

def scan_folder(ws_id: str) -> dict:
    """Walk workspace scripts/ dir, return hierarchical tree with is_sql flag."""
    ws_dir = get_workspace_dir(ws_id)
    scripts_dir = ws_dir / "scripts"
    if not scripts_dir.exists():
        return {"name": "root", "type": "directory", "children": []}
    
    def _walk(path: Path, rel: str = ""):
        entry = {
            "name": path.name,
            "path": str(path.relative_to(scripts_dir)),
            "type": "directory" if path.is_dir() else "file",
        }
        if path.is_file():
            ext = path.suffix.lower()
            entry["is_sql"] = ext in SQL_EXTENSIONS
        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name)):
                children.append(_walk(child))
            entry["children"] = children
        return entry
    
    return _walk(scripts_dir)


def index_scripts(ws_id: str, script_paths: list[str]) -> dict:
    """Analyze selected scripts, build table_index and field_index.
    
    For each script:
      1. Read SQL from workspace/scripts/{path}
      2. Call run_full_analysis()
      3. Extract table/column variables
      4. Build indexes
    
    Returns: {table_index, field_index, script_count, precomputed_count,
              resolution_stats} — resolution_stats carries the R20 coverage
              numbers aggregated from per-script extraction + the S4b
              cross-script schema pass.
    """
    from app.extractor.adapter import run_full_analysis

    table_index = {}   # table_name -> {fields: set, scripts: set}
    field_index = {}   # field_name -> {tables: set, scripts: set}
    script_count = 0
    precomputed = 0
    errors = []
    total = len(script_paths)
    # L3: explicit fresh start — clears any errors from a previous run.
    _set_progress(ws_id, 0, total, "analyzing", errors=[])

    # R20 / S4 (Phase 2) accumulation: the extractor's per-script resolution
    # counters + S4b (cross-script schema resolution) inputs, aggregated at
    # index time.
    total_columns = 0     # sum of per-script column-variable counts
    extractor_unresolved = set()  # R20: fields the extractor could not resolve (S1-S3, S5/S6 excluded)
    stats_seen = False    # any script carried resolution_stats (fallback gate)
    by_strategy = {"plain_alias": 0, "expr_alias": 0, "scope": 0,
                   "schema": 0, "sys": 0, "other": 0}
    # S4b (Phase 2 — AUTO-RESOLUTION) accumulation: the workspace schema map
    # M_ws (union of the extractor's per-script script_schemas) plus the
    # per-script schema_candidates records (S4a residuals — still-unresolved
    # bare columns in ≥2-table scopes). S4b re-tests each candidate ONLY
    # against its OWN visible_tables — never workspace-global uniqueness.
    m_ws = {}                    # canonical table -> set(columns)
    schema_candidate_records = []  # (script, {field, visible_tables, loc, ...})
    schema_evidence_by_script = {}  # script -> {table_lower: {col_lower: line_int}}
    r6_collision_total = 0       # summed per-script r6_collision (S4a counter)
    s4c_seen = False             # any script carried the new S4 keys
    cache_by_script = {}         # rel_path -> analysis cache path (S4b updates)

    for i, rel_path in enumerate(script_paths):
        sp = get_script_path(ws_id, rel_path)
        if not sp or not sp.exists():
            errors.append({"script": rel_path, "error": "File not found"})
            # L3: surface the error in progress without resetting it.
            _set_progress(ws_id, i, total, "analyzing", errors=errors)
            continue

        try:
            sql_text = sp.read_text(encoding="utf-8", errors="replace")
            result = run_full_analysis(sql_text, rel_path, ws_id=ws_id)
            script_count += 1
            _set_progress(ws_id, i + 1, total, "analyzing")

            # Cache analysis result
            cache_dir = get_workspace_dir(ws_id) / "cache"
            import hashlib
            cache_key = hashlib.md5((rel_path + sql_text).encode()).hexdigest()[:12]
            cache_path = cache_dir / f"analysis_{cache_key}.json"
            cache_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            cache_by_script[rel_path] = str(cache_path)  # S4b persists attributions

            # ── R20: aggregate per-script resolution stats ──
            # The extractor emits `resolution_stats` in new analyses; old
            # caches / mid-flight versions may not — read defensively.
            # Reviewer finding (R20): the index-level orphan set must follow
            # the extractor's OWN `unresolved` lists (single source of truth)
            # — they exclude S5/S6-marked and CTE/alias-resolved fields, which
            # the tables==[] test alone cannot distinguish.
            rs = result.get("resolution_stats")
            stats_seen = isinstance(rs, dict)
            if stats_seen:
                total_columns += rs.get("total_columns", 0) or 0
                rb = rs.get("resolved_by")
                if isinstance(rb, dict):
                    for _k in by_strategy:
                        by_strategy[_k] += rb.get(_k, 0) or 0
                for _f in rs.get("unresolved", []) or []:
                    if isinstance(_f, str):
                        extractor_unresolved.add(_f)

                # ── S4b inputs: SELECT-side schema evidence (Phase 2) ──
                # The extractor (S4a) emits `schema_candidates` (S4a
                # residuals), `script_schemas` and `r6_collision` with new
                # analyses; old caches lack them (or carry the Phase-0
                # list-shaped script_schemas) — read defensively. M_ws (the
                # S4b map) is the union of all scripts' script_schemas. NEW
                # shape: {table: {col: evidence_line_int}} — membership
                # `field in script_schemas[t]` works on dict keys, and the
                # line is the schema-EVIDENCE provenance for the report.
                # OLD shape: {table: [cols]} — same membership, no lines.
                ss4c = rs.get("script_schemas")
                if isinstance(ss4c, dict):
                    ev_map = {}
                    for _t, _cols in ss4c.items():
                        if not isinstance(_t, str):
                            continue
                        if isinstance(_cols, dict):
                            # new shape: {col: evidence_line_int}
                            m_ws.setdefault(_t, set()).update(
                                str(c) for c in _cols if isinstance(c, str))
                            ev_rows = {}
                            for _c, _ln in _cols.items():
                                if (isinstance(_c, str)
                                        and isinstance(_ln, (int, float))
                                        and not isinstance(_ln, bool)):
                                    ev_rows[_c.lower()] = int(_ln)
                            if ev_rows:
                                ev_map.setdefault(_t.lower(), {}).update(ev_rows)
                        elif isinstance(_cols, (list, tuple, set)):
                            # old shape: column list, no provenance
                            m_ws.setdefault(_t, set()).update(
                                c for c in _cols if isinstance(c, str))
                    if ev_map:
                        schema_evidence_by_script[rel_path] = ev_map
                sc4c = rs.get("schema_candidates")
                if isinstance(sc4c, list):
                    for _c in sc4c:
                        if isinstance(_c, dict):
                            schema_candidate_records.append((rel_path, _c))
                _r6 = rs.get("r6_collision")
                if isinstance(_r6, (int, float)) and not isinstance(_r6, bool):
                    r6_collision_total += int(_r6)
                # N3 (review): the Phase-2 report gate requires ALL THREE S4
                # keys in the same analysis — a partially-upgraded cache
                # (e.g. script_schemas only) must keep the Phase-1 block and
                # a zeroed summary rather than print a misleading zero line.
                s4c_seen = (s4c_seen
                            or ("schema_candidates" in rs
                                and "script_schemas" in rs
                                and "r6_collision" in rs))

            # Pre-compute graph
            try:
                from app.services.graph_service import build_graph_data
                graph_data = build_graph_data(result)
                # Bug 48: Add alias_map to graph cache so consumers don't rebuild it
                graph_data["alias_map"] = {
                    v["name"]: v["source_tables"][0]
                    for v in result.get("variables", [])
                    if v.get("source_tables") and v.get("variable_type") in ("table", "view", "cte")
                }
                # M2: write under the canonical name L2 reads (graph_3_2_15_) so
                # index-time precomputation is actually used by L2 cache hits.
                graph_cache_path = cache_dir / f"graph_3_2_15_{cache_key}.json"
                # Item 4: cache format version — consumers warn on stale caches
                graph_data["format_version"] = 3
                graph_cache_path.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False))
                # M2: also precompute table_schemas (Bug 25 path) so L2 cache hits
                # have schemas without re-running analysis.
                from app.extractor.schema_inference import infer_table_schemas
                schemas_cache_path = cache_dir / f"schemas_{cache_key}.json"
                if not schemas_cache_path.exists():
                    schemas_cache_path.write_text(json.dumps(
                        infer_table_schemas(result.get("variables", []),
                                            result.get("dependencies", [])),
                        default=str))
                precomputed += 1
            except Exception:
                pass  # graph pre-computation is optional

            # Build indexes from variables
            variables = result.get("variables", [])
            # Bug 49: map SQL aliases → physical tables ("c" → "crm_customers")
            # so column variables register against the real table, not just the alias
            alias_to_physical = {}
            cte_names = set()  # R20 reviewer fix: CTEs are script-scoped —
            for v in variables:
                if v.get("variable_type") in ("table", "view", "cte") and v.get("source_tables"):
                    alias_to_physical[v.get("name", "")] = v.get("source_tables", [None])[0]
                if v.get("variable_type") == "cte":
                    cte_names.add(v.get("name", ""))
            for v in variables:
                vt = v.get("variable_type", "")
                name = v.get("name", "")

                if vt == "table":
                    table_index.setdefault(name, {"fields": set(), "scripts": set()})
                    table_index[name]["scripts"].add(rel_path)

                elif vt == "column":
                    field_name = name.split(".", 1)[-1] if "." in name else name
                    table_name = name.split(".", 1)[0] if "." in name else ""
                    # R20: unqualified columns resolved by the extractor (S1-S3)
                    # carry source_tables — surface them in the index too.
                    # Skip ⟐-prefixed entries (output containers + S5/S6 markers
                    # are script-scoped) and CTE names (script-scoped; must not
                    # become workspace-wide tables or S4 candidates).
                    if not table_name:
                        for _st in v.get("source_tables", []):
                            if _st and not _st.startswith("⟐") and _st not in cte_names:
                                table_name = _st
                                break
                    field_index.setdefault(field_name, {"tables": set(), "scripts": set()})
                    field_index[field_name]["scripts"].add(rel_path)
                    # Bug 49: also register the physical table (alias → canonical),
                    # so autocomplete surfaces crm_customers.customer_id, not just c.customer_id
                    if table_name:
                        physical = alias_to_physical.get(table_name, table_name)
                        for tname in {table_name, physical}:
                            field_index[field_name]["tables"].add(tname)
                            table_index.setdefault(tname, {"fields": set(), "scripts": set()})
                            table_index[tname]["fields"].add(field_name)

            # Bug 41: Cross-reference DML dependencies so that INSERT column
            # names (e.g., total_amount) are indexed alongside SELECT aliases
            # (e.g., total) for autocomplete. This lets users find fields by
            # either the INSERT column name or the SELECT alias.
            dependencies = result.get("dependencies", [])
            if dependencies:
                var_by_id = {v2.get("id"): v2 for v2 in variables}
                for dep in dependencies:
                    if dep.get("relationship") != "DML":
                        continue
                    src = var_by_id.get(dep.get("source_id"))
                    tgt = var_by_id.get(dep.get("target_id"))
                    if not (src and tgt):
                        continue
                    if src.get("variable_type") != "column" or tgt.get("variable_type") != "column":
                        continue
                    src_name = src.get("name", "")
                    tgt_name = tgt.get("name", "")
                    # Target: "daily_summary.total_amount" -> table=daily_summary, field=total_amount
                    tgt_field = tgt_name.split(".", 1)[-1] if "." in tgt_name else tgt_name
                    tgt_table = tgt_name.split(".", 1)[0] if "." in tgt_name else ""
                    # Source: "total" or "analytics_orders.total" -> field=total
                    src_field = src_name.split(".", 1)[-1] if "." in src_name else src_name
                    if not tgt_table:
                        continue
                    # Map both names to the INSERT target table
                    table_index.setdefault(tgt_table, {"fields": set(), "scripts": set()})
                    table_index[tgt_table]["fields"].add(src_field)
                    table_index[tgt_table]["fields"].add(tgt_field)
                    # Index both names in field_index with target table
                    for fn in (src_field, tgt_field):
                        field_index.setdefault(fn, {"tables": set(), "scripts": set()})
                        field_index[fn]["tables"].add(tgt_table)
                        field_index[fn]["scripts"].add(rel_path)

        except Exception as e:
            errors.append({"script": rel_path, "error": str(e)})
            # L3: keep last progress + the error (was: _set_progress wiped
            # the errors list back to zero on every failure).
            _set_progress(ws_id, i + 1, total, "analyzing", errors=errors)


    # ── S4b: cross-script schema resolution (Phase 2 — AUTO) ──
    # REPLACES the scope-blind index S4 loop (Phase-1 audit PASSED,
    # 2026-08-06). Candidates are the extractor's per-script
    # `schema_candidates` (S4a residuals — still-unresolved bare columns in
    # ≥2-table scopes, each carrying its OWN visible_tables). Each is
    # re-tested against M_ws (union of all scripts' script_schemas) but
    # ONLY within the candidate's own scope: a field known only in table T
    # is never attributed to T in a statement that doesn't reference it
    # (never-guess — no workspace-global uniqueness fallback).
    # Rule per candidate:
    #   1. R6 guard — lower(field) ∈ lower(visible_tables) → never attribute
    #      (S4a already counted it in r6_collision; S4b only refuses).
    #   2. owners = {t ∈ visible_tables : field ∈ M_ws[t]} — whole-name,
    #      case-insensitive equality (R4: "id" never matches "customer_id").
    #   3. len(owners) == 1 → attribute; 0 (evidence absent / table not
    #      visible) or ≥2 (ambiguous) → stays unresolved + reported.
    # L2 (review): the owner check matches TABLE names EXACTLY first — a
    # case-insensitive fallback applies only when the visible table has NO
    # exact entry in m_ws (distinct case variants like Orders/orders must
    # never be merged into a shared evidence pool). Field names stay
    # case-insensitive (R4).
    def _table_owns(t, field_lower):
        cols = m_ws.get(t)  # exact key first
        if cols is None:
            variants = [c2 for t2, c2 in m_ws.items()
                        if t2.lower() == t.lower() and t2 != t]
            if len(variants) == 1:
                cols = variants[0]
            else:
                return False  # 0 or ≥2 case variants → no evidence (never guess)
        return field_lower in {c.lower() for c in cols}

    s4b_resolved = []  # (field, owner, cand_script, cand_record) — S4b additions
    for _srec, _crec in schema_candidate_records:
        if not isinstance(_crec, dict):
            continue
        _f = _crec.get("field")
        visible = [t for t in (_crec.get("visible_tables") or [])
                   if isinstance(t, str) and t]
        if not isinstance(_f, str) or not _f or not visible:
            continue  # malformed record — never guess on it
        fdata = field_index.get(_f)
        if fdata and fdata.get("tables"):
            continue  # already attributed (S1–S3/S4a or another script) — no-op
        if _f.lower() in {t.lower() for t in visible}:
            continue  # R6 guard — field == visible table: never attribute
        owners = [t for t in visible if _table_owns(t, _f.lower())]
        if len(owners) != 1:
            continue  # 0 owners (evidence absent / not visible) or ≥2 → stay
        owner = owners[0]
        # L1 (review): the owner must ALREADY be a real index table (it is a
        # visible table of the statement, so it should be — unless an
        # alias-resolution failure leaked an alias name here). Never
        # fabricate a table_index entry for an unindexed owner: leave the
        # candidate unresolved (never guess) and let it surface in the report.
        if owner not in table_index:
            continue
        # Index-level attribution (same mechanics as the old loop, but the
        # candidate's own scope replaces workspace-global uniqueness).
        field_index.setdefault(_f, {"tables": set(), "scripts": set()})
        field_index[_f]["tables"].add(owner)
        table_index[owner]["fields"].add(_f)
        by_strategy["schema"] += 1
        extractor_unresolved.discard(_f)  # out of the per-script unresolved lists
        # Persist into the analysis cache: var attribution + resolution_stats
        # (unresolved drop, schema +1, candidate removal) so cache consumers
        # (L1/L2) see the resolution too.
        _apply_s4b_cache_update(cache_by_script.get(_srec), _f, owner, visible)
        s4b_resolved.append((_f, owner, _srec, _crec))
    s4b_unique_owners = len(s4b_resolved)

    # P1: Build pair_index[(table,field)] → {scripts} for fast seed-script lookup.
    # Used by Algorithm 2 step 2a to find seed scripts without scanning all data.
    # Built AFTER S4 so schema attributions are included.
    cache_dir = get_workspace_dir(ws_id) / "cache"
    pair_index = {}
    for field_name, fdata in field_index.items():
        for table_name in fdata.get("tables", []):
            key = f"{table_name}.{field_name}"
            pair_index.setdefault(key, set()).update(fdata.get("scripts", []))

    # Cache pair_index
    (cache_dir / "pair_index.json").write_text(json.dumps(
        {k: sorted(v) for k, v in pair_index.items()}, indent=2))

    # Convert sets to sorted lists for JSON
    for ti in table_index.values():
        ti["fields"] = sorted(ti["fields"])
        ti["scripts"] = sorted(ti["scripts"])
    for fi in field_index.values():
        fi["tables"] = sorted(fi["tables"])
        fi["scripts"] = sorted(fi["scripts"])

    # Cache indexes
    cache_dir = get_workspace_dir(ws_id) / "cache"
    (cache_dir / "table_index.json").write_text(json.dumps(table_index, indent=2))
    (cache_dir / "field_index.json").write_text(json.dumps(field_index, indent=2))

    # ── R20: orphan resolution coverage report (supersedes Bug 54) ──
    # Post-S4 orphans = fields with no table attribution. The report is the
    # RESIDUAL layer of the resolution pipeline (S1–S4): only fields the
    # extractor genuinely cannot attribute are listed, with SQL evidence,
    # alongside the coverage numbers (resolved / total column variables).
    # Reviewer fix: the orphan set follows the extractor's own `unresolved`
    # lists (excludes S5/S6-marked and CTE/alias-resolved fields). When the
    # analysis caches lack resolution_stats (old data), fall back to the
    # tables==[] test.
    if stats_seen:
        # Extractor-driven: its `unresolved` already excludes S5/S6-marked,
        # CTE/alias-resolved fields. Post-S4 attribution removes more.
        orphan_fields = {fname: sorted(fdata.get("scripts", []))
                         for fname, fdata in field_index.items()
                         if fname in extractor_unresolved
                         and not fdata.get("tables")}
    else:
        # Old caches without resolution_stats: tables==[] fallback.
        orphan_fields = {fname: sorted(fdata.get("scripts", []))
                         for fname, fdata in field_index.items()
                         if not fdata.get("tables")}
    (cache_dir / "orphan_fields.json").write_text(json.dumps(orphan_fields, indent=2))

    # E1 (reviewer): fields resolved to script-scoped containers (⟐ output,
    # CTE) are counted resolved by the extractor but have NO usable table in
    # the workspace index — and were invisible (not attributed, not reported).
    # Surface them as a distinct bucket so nothing is hidden.
    no_table_fields = {fname for fname, fdata in field_index.items()
                       if not fdata.get("tables")}
    container_resolved = sorted(no_table_fields - set(orphan_fields))

    # ── S4b owner lines for the report: schema-EVIDENCE provenance ──
    # One line per S4b attribution (field → owner). With the new
    # dict-of-dicts script_schemas (audit recommendation 2) the line shows
    # the SCHEMA-EVIDENCE line (the DDL / qualified-ref line that proves the
    # owner), plus the bare-use loc when it differs; without provenance
    # (old-shape caches) the Phase-1 format is kept (candidate script + loc).
    s4b_owner_lines = []  # (field, owner, script, loc_label, visible_txt)
    for _f, owner, _srec, _crec in sorted(s4b_resolved, key=lambda r: r[0]):
        visible_names = [t for t in (_crec.get("visible_tables") or [])
                         if isinstance(t, str) and t]
        vis_txt = (", visible: %s" % ", ".join(visible_names[:6])
                   if visible_names else "")
        ev_script, ev_line = _evidence_loc(owner, _f, schema_evidence_by_script)
        if ev_script is None or ev_line is None:
            # no provenance (old-shape script_schemas) → Phase-1 format:
            # candidate script + loc (string/missing loc → SQL line search).
            loc_label = _loc_label(ws_id, _srec, _f, _crec.get("loc"))
            s4b_owner_lines.append((_f, owner, _srec, loc_label, vis_txt))
            continue
        loc_label = "L%d" % ev_line
        used_label = _loc_label(ws_id, _srec, _f, _crec.get("loc"))
        if used_label and (ev_script != _srec or loc_label != used_label):
            loc_label += ", used: %s %s" % (_srec, used_label)
        s4b_owner_lines.append((_f, owner, ev_script, loc_label, vis_txt))
    s4b_unique_owners = len(s4b_owner_lines)

    # L3: don't shadow `total` (script count) — the "done" progress below
    # must report scripts, not column variables.
    total_cols = total_columns
    unresolved = len(orphan_fields)
    resolved = max(0, total_cols - unresolved)
    coverage_pct = round(resolved / total_cols * 100, 1) if total_cols else 100.0
    resolution_stats = {
        "total_columns": total_cols,
        "resolved": resolved,
        "unresolved": unresolved,
        "container_resolved": len(container_resolved),
        "coverage_pct": coverage_pct,
        "by_strategy": dict(by_strategy),
    }
    _push_resolution_report(ws_id, resolution_stats, orphan_fields,
                            container_resolved,
                            s4c_seen=s4c_seen,
                            n_cand=len(schema_candidate_records),
                            n_owner=s4b_unique_owners,
                            r6_total=r6_collision_total,
                            owner_lines=s4b_owner_lines)

    # Update workspace meta
    ws_dir = get_workspace_dir(ws_id)
    meta = json.loads((ws_dir / "meta.json").read_text())
    meta["indexed"] = True
    meta["indexed_scripts"] = script_paths
    meta["indexed_at"] = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    (ws_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    _set_progress(ws_id, total, total, "done")
    return {
        "table_index": table_index,
        "field_index": field_index,
        "script_count": script_count,
        "precomputed_count": precomputed,
        "errors": errors,
        "orphan_field_count": len(orphan_fields),
        "orphan_field_samples": list(sorted(orphan_fields))[:20],
        "resolution_stats": resolution_stats,
        # S4b (Phase 2): SELECT-side candidate summary — N = candidate
        # records remaining after S4a (the S4b input), M = resolved by S4b
        # (unique visible owner found), K = summed per-script r6_collision
        # (S4a counter; S4b only refuses r6 candidates, never recounts).
        # Zeroed on old caches (no new keys) so consumers get a stable shape.
        "schema_candidates_summary": {
            "total": len(schema_candidate_records),
            "unique_owner": s4b_unique_owners,
            "r6_collision": r6_collision_total,
        },
    }


def _resolve_orphan_script(ws_id: str, name: str):
    """Locate a script file by index name (path, basename, ±.sql).

    R5: shared resolver — the filter's SQL-evidence diagnostics use the
    same tolerance (see filter_service.resolve_script).
    """
    return resolve_script(ws_id, name)


def _loc_label(ws_id: str, script: str, field: str, loc) -> str:
    """Evidence loc for an S4b owner line: an int loc renders as L<int>;
    a string loc (or a missing loc) reuses the report's SQL-evidence line
    search — first line of `script` mentioning the field — so the evidence
    stays consistent with the UNRESOLVED section's mechanism.
    """
    if isinstance(loc, int) and not isinstance(loc, bool):
        return "L%d" % loc
    sp = _resolve_orphan_script(ws_id, script)
    if sp:
        try:
            sql_txt = sp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            sql_txt = ""
        needle = field.lower()
        for i, ln in enumerate(sql_txt.split("\n")):
            if needle in ln.lower():
                return "L%d" % (i + 1)
    return str(loc) if loc is not None else ""


def _evidence_loc(owner: str, field: str,
                  schema_evidence_by_script: dict) -> tuple:
    """Schema-EVIDENCE (script, line) for an S4b-resolved (owner, field).

    Scans the per-script script_schemas provenance (the new dict-of-dicts
    shape, {table: {col: evidence_line_int}}): scripts whose name suggests
    DDL ("table" / "ddl" / "schema") come first, then alphabetical order —
    deterministic. Returns (script, line) or (None, None) when no
    provenance exists (old-shape list script_schemas).
    """
    owner_l = owner.lower()
    field_l = field.lower()
    for _s, _ev in sorted(schema_evidence_by_script.items(),
                          key=lambda kv: (0 if any(h in kv[0].lower()
                                                   for h in ("table", "ddl", "schema"))
                                          else 1, kv[0])):
        ln = (_ev.get(owner_l) or {}).get(field_l)
        if ln is not None and not isinstance(ln, bool):
            return _s, int(ln)
    return None, None


def _apply_s4b_cache_update(cache_path, field: str, owner: str,
                            visible: list) -> None:
    """S4b: persist an index-time attribution into the script's analysis
    cache — var.source_tables, resolution_stats (field dropped from
    `unresolved`, `resolved_by["schema"]` +1, the candidate record removed).
    Best-effort: a stale/missing cache is skipped — the in-memory indexes
    are already updated, and a re-index re-extracts from scratch.
    """
    if not cache_path:
        return
    try:
        cdata = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(cdata, dict):
        return
    changed = False
    for v in cdata.get("variables", []) or []:
        if (isinstance(v, dict)
                and v.get("variable_type") == "column"
                and v.get("name") == field
                and not v.get("source_tables")):
            v["source_tables"] = [owner]
            changed = True
    rs = cdata.get("resolution_stats")
    if isinstance(rs, dict):
        ul = rs.get("unresolved")
        if isinstance(ul, list) and field in ul:
            ul.remove(field)
            rb = rs.setdefault("resolved_by", {})
            rb["schema"] = (rb.get("schema", 0) or 0) + 1
            changed = True
        cands = rs.get("schema_candidates")
        if isinstance(cands, list):
            vis_key = sorted(t.lower() for t in visible)
            rs["schema_candidates"] = [
                c for c in cands
                if not (isinstance(c, dict) and c.get("field") == field
                        and sorted((t.lower() for t in
                                    (c.get("visible_tables") or [])
                                    if isinstance(t, str))) == vis_key)]
    if changed:
        try:
            Path(cache_path).write_text(
                json.dumps(cdata, indent=2, ensure_ascii=False))
        except Exception:
            pass  # cache persistence is best-effort


def _push_resolution_report(ws_id: str, stats: dict, orphan_fields: dict,
                            container_resolved: list | None = None,
                            *, s4c_seen: bool = False, n_cand: int = 0,
                            n_owner: int = 0, r6_total: int = 0,
                            owner_lines: list | None = None):
    """R20: coverage diagnostic — resolved vs total column variables.

    Supersedes the Bug-54 ORPHAN FIELD REPORT (same SQL-evidence mechanism
    for the residual orphans). Always pushed, even when every column is
    resolved. Shows up to 10 fields (name + first script + up to 3 SQL
    lines from that script mentioning the field, stripped to ~70 chars).
    E1 (reviewer): "resolved to output container" fields (⟐ output / CTE —
    script-scoped, no usable workspace table) are surfaced as a distinct
    bucket so nothing is invisible.

    S4b (Phase 2, AUTO-RESOLUTION): when new analyses carry the S4a keys
    (s4c_seen), a schema-candidates summary line (`schema candidates: N
    (unique visible owner found: M) | r6 collision: K`) plus one owner line
    per S4b attribution follows the strategy lines. M = S4b additions;
    N = candidate records remaining after S4a. Owner lines show the
    schema-EVIDENCE script/line (DDL / qualified ref — dict-of-dicts
    provenance) plus the bare-use loc when it differs; old-shape caches
    without provenance keep the Phase-1 candidate-loc format. Old caches
    without the keys produce a byte-identical block.
    """
    W = 80
    total = stats.get("total_columns", 0)
    resolved = stats.get("resolved", 0)
    coverage_pct = stats.get("coverage_pct", 0)
    by = stats.get("by_strategy", {})
    names = sorted(orphan_fields)
    n = len(names)
    cont = sorted(container_resolved or [])
    nc = len(cont)
    lines = ["┌─ ORPHAN RESOLUTION REPORT "
             + "─" * max(0, W - len("┌─ ORPHAN RESOLUTION REPORT ") - 1) + "┐"]
    lines.append(("│ column vars: %d | resolved: %d (%g%%) |"
                  % (total, resolved, coverage_pct)).ljust(W - 1) + "│")
    lines.append(("│   unresolved: %d | resolved-to-container (no table): %d"
                  % (n, nc)).ljust(W - 1) + "│")
    lines.append(("│   by strategy (attribution events, not unique vars): "
                  "pa=%d ea=%d scope=%d schema=%d"
                  % (by.get("plain_alias", 0), by.get("expr_alias", 0),
                     by.get("scope", 0), by.get("schema", 0))).ljust(W - 1) + "│")
    lines.append(("│   (sys=%d other=%d marked expected)"
                  % (by.get("sys", 0), by.get("other", 0))).ljust(W - 1) + "│")
    if nc:
        lines.append(("│   container-resolved sample: %s"
                      % ", ".join(cont[:5])).ljust(W - 1) + "│")
    if s4c_seen:
        # S4 (Phase 1): SELECT-side schema candidates — REPORT ONLY. Only
        # shown when new analyses carry the keys; old caches keep the
        # pre-Phase-1 block byte-identical. Owner lines are sorted by field
        # name (caller builds them from `sorted(orphan_fields)`).
        lines.append(("│   schema candidates: %d (unique visible owner found:"
                      " %d) | r6 collision: %d" % (n_cand, n_owner, r6_total))
                     .ljust(W - 1) + "│")
        for fname, owner, script, loc_label, vis_txt in (owner_lines or []):
            loc_part = (" %s" % loc_label) if loc_label else ""
            # N2 (review): fname/owner/script are truncated, but a long
            # visible-list suffix (6 tables) still overflows the W=80 box —
            # drop the suffix when the line is tight, and clip the content
            # as the final guarantee. The evidence fragment (script + line)
            # always survives.
            base = ("│   field: %s → %s (evidence: %s%s%s)"
                    % (fname[:18], owner[:18], script[:24],
                       loc_part, vis_txt))
            if len(base) > W - 2 and vis_txt:
                base = ("│   field: %s → %s (evidence: %s%s)"
                        % (fname[:18], owner[:18], script[:24], loc_part))
            lines.append(base[:W - 2].ljust(W - 1) + "│")
    lines.append("│" + "─" * (W - 2) + "│")
    if n:
        lines.append(("│ UNRESOLVED orphans — possible bad cases, check SQL:")
                     .ljust(W - 1) + "│")
        for fname in names[:10]:
            script = (orphan_fields[fname] or [""])[0]
            lines.append(("│ field: %s   script: %s"
                          % (fname[:26], script[:32])).ljust(W - 1) + "│")
            # Line search ONLY for reported fields (keep indexing fast)
            sp = _resolve_orphan_script(ws_id, script)
            if sp:
                try:
                    sql_txt = sp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    sql_txt = ""
                needle = fname.lower()
                hits = [(i + 1, ln) for i, ln in enumerate(sql_txt.split("\n"))
                        if needle in ln.lower()]
                for lineno, ln in hits[:3]:
                    lines.append(("│ %s" % ("   L%d: %s" % (lineno, ln.strip()))[:70])
                                 .ljust(W - 1) + "│")
        if n > 10:
            lines.append(("│ ... %d more" % (n - 10)).ljust(W - 1) + "│")
    lines.append("└" + "─" * (W - 2) + "┘")
    for line in lines:
        _push(ws_id, "profile", line)


def autocomplete(index: dict, type_: str, query: str) -> list[str]:
    """Return matching names from the index (case-insensitive substring, max 20)."""
    if not query:
        return sorted(index.keys())[:20]
    q = query.lower()
    matches = [k for k in index if q in k.lower()]
    return sorted(matches)[:20]


def tables_for_field(index: dict, field: str) -> list[str]:
    """Return all tables containing the given field."""
    entry = index.get(field, {})
    return entry.get("tables", [])


def fields_for_table(index: dict, table: str) -> list[str]:
    """Return all fields of the given table."""
    entry = index.get(table, {})
    return entry.get("fields", [])


def get_index_status(ws_id: str) -> dict:
    """Return current indexing status."""
    ws_dir = get_workspace_dir(ws_id)
    meta_path = ws_dir / "meta.json"
    if not meta_path.exists():
        return {"indexed": False}
    meta = json.loads(meta_path.read_text())
    return {
        "indexed": meta.get("indexed", False),
        "script_count": len(meta.get("indexed_scripts", [])),
        "indexed_at": meta.get("indexed_at"),
    }
