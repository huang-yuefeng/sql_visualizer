"""Folder index service — scan directory tree, build table/field indexes."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from app.services.workspace_service import get_workspace_dir, get_script_path
from app.services.logger import _push

SQL_EXTENSIONS = {".sql"}


# Progress tracking for polling
_INDEX_PROGRESS = {}  # ws_id -> {current, total, phase, errors}

def _set_progress(ws_id: str, current: int, total: int, phase: str):
    _INDEX_PROGRESS[ws_id] = {"current": current, "total": total, "phase": phase, "errors": []}

def get_index_progress(ws_id: str) -> dict:
    return _INDEX_PROGRESS.get(ws_id, {"current": 0, "total": 0, "phase": "idle"})

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
              numbers aggregated from per-script extraction + the S4 pass.
    """
    from app.extractor.adapter import run_full_analysis

    table_index = {}   # table_name -> {fields: set, scripts: set}
    field_index = {}   # field_name -> {tables: set, scripts: set}
    script_count = 0
    precomputed = 0
    errors = []
    total = len(script_paths)
    _set_progress(ws_id, 0, total, "analyzing")

    # R20 / S4 (Phase 2) accumulation: per-script inferred schemas + the
    # extractor's per-script resolution counters, aggregated at index time.
    script_schemas = []   # list of {table -> set(fields)}
    total_columns = 0     # sum of per-script column-variable counts
    extractor_unresolved = set()  # R20: fields the extractor could not resolve (S1-S3, S5/S6 excluded)
    stats_seen = False    # any script carried resolution_stats (fallback gate)
    by_strategy = {"plain_alias": 0, "expr_alias": 0, "scope": 0,
                   "schema": 0, "sys": 0, "other": 0}

    for i, rel_path in enumerate(script_paths):
        sp = get_script_path(ws_id, rel_path)
        if not sp or not sp.exists():
            errors.append({"script": rel_path, "error": "File not found"})
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

            # ── S4 input (Phase 2): per-script inferred schemas ──
            # schema_inference expects attribute-style objects; the analysis
            # JSON holds plain dicts → adapt locally so extraction stays
            # untouched. Best-effort: a failing script just skips S4.
            schemas = {}
            try:
                from app.extractor.schema_inference import infer_table_schemas
                obj_vars = [SimpleNamespace(**v)
                            for v in result.get("variables", []) if isinstance(v, dict)]
                obj_deps = [SimpleNamespace(**d)
                            for d in result.get("dependencies", []) if isinstance(d, dict)]
                schemas = infer_table_schemas(obj_vars, obj_deps) or {}
            except Exception:
                schemas = {}
            script_schemas.append(schemas)

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
            _set_progress(ws_id, i + 1, total, "analyzing")


    # ── S4: schema-based resolution (Phase 2 — index time) ──
    # Bare columns no earlier strategy could attribute get one last pass:
    # if EXACTLY ONE physical table across the workspace has the field in
    # its inferred schema, attribute it. Schema field names are exact, so
    # set membership already enforces the R4 word-boundary invariant
    # (`id` never matches `customer_id`).
    schema_map = {}   # table -> set(fields), aggregated across scripts
    for per_script in script_schemas:
        for tbl, fields in per_script.items():
            schema_map.setdefault(tbl, set()).update(fields)

    schema_resolved = 0
    for fname, fdata in field_index.items():
        if fdata.get("tables"):
            continue  # only truly orphaned pre-S4 fields are candidates
        if fname in table_index:
            continue  # R6: field-name == table-name collisions are never auto-attributed
        # Candidates are PHYSICAL tables (present in the workspace index) —
        # virtual tables (⟐ output) and CTE names are script-scoped and must
        # not become workspace-wide autocomplete entries.
        candidates = [tbl for tbl, fields in schema_map.items()
                      if tbl in table_index and fname in fields]
        if len(candidates) == 1:
            tbl = candidates[0]
            fdata["tables"].add(tbl)
            table_index.setdefault(tbl, {"fields": set(), "scripts": set()})
            table_index[tbl]["fields"].add(fname)
            schema_resolved += 1
    by_strategy["schema"] += schema_resolved

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

    total = total_columns
    unresolved = len(orphan_fields)
    resolved = max(0, total - unresolved)
    coverage_pct = round(resolved / total * 100, 1) if total else 100.0
    resolution_stats = {
        "total_columns": total,
        "resolved": resolved,
        "unresolved": unresolved,
        "container_resolved": len(container_resolved),
        "coverage_pct": coverage_pct,
        "by_strategy": dict(by_strategy),
    }
    _push_resolution_report(ws_id, resolution_stats, orphan_fields,
                            container_resolved)

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
    }


def _resolve_orphan_script(ws_id: str, name: str):
    """Locate a script file by index name (path, basename, ±.sql).

    Same tolerance as the filter's _resolve_script in workspace.py: try
    as-is, with .sql appended, and basename variants, then rglob fallback.
    """
    if not name:
        return None
    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    cands = [name]
    if not name.lower().endswith(".sql"):
        cands.append(name + ".sql")
    for c in list(cands):
        cands.append(os.path.basename(c))
    for c in cands:
        p = scripts_dir / c
        if p.exists():
            return p
    for p in scripts_dir.rglob("*.sql"):
        if p.name in cands or str(p.relative_to(scripts_dir)) in cands:
            return p
    return None


def _push_resolution_report(ws_id: str, stats: dict, orphan_fields: dict,
                            container_resolved: list | None = None):
    """R20: coverage diagnostic — resolved vs total column variables.

    Supersedes the Bug-54 ORPHAN FIELD REPORT (same SQL-evidence mechanism
    for the residual orphans). Always pushed, even when every column is
    resolved. Shows up to 10 fields (name + first script + up to 3 SQL
    lines from that script mentioning the field, stripped to ~70 chars).
    E1 (reviewer): "resolved to output container" fields (⟐ output / CTE —
    script-scoped, no usable workspace table) are surfaced as a distinct
    bucket so nothing is invisible.
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
