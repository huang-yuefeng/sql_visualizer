"""Workspace router — zip upload, workspace CRUD."""
from fastapi import APIRouter, HTTPException, UploadFile, File
from app.services.logger import _push, _ts
import csv
import io
import os
from app.services.workspace_service import (
    create_workspace, get_workspace, delete_workspace,
    get_workspace_dir, cleanup_all_workspaces,
)
from app.services.export_config_service import (
    get_export_config, save_export_config, reset_export_config,
    apply_export_config, DEFAULT_CONFIG,
)
from app.services.folder_index_service import (
    scan_folder, index_scripts, get_index_status,
    get_index_progress,
)

router = APIRouter(tags=["workspace"])


@router.post("/workspace")
async def upload_workspace(file: UploadFile):
    """Upload a zip file, create workspace. Auto-scans and returns file tree."""
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(status_code=400, detail="Only .zip files accepted")
    
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 100MB)")
    
    try:
        ws_id = create_workspace(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract zip: {str(e)}")
    
    # Auto-scan
    tree = scan_folder(ws_id)
    
    return {
        "workspace_id": ws_id,
        "file_tree": tree,
    }


@router.get("/workspace/{ws_id}")
async def get_workspace_info(ws_id: str):
    """Get workspace metadata and status."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    status = get_index_status(ws_id)
    ws["index_status"] = status
    return ws


@router.delete("/workspace/{ws_id}")
async def delete_workspace_endpoint(ws_id: str):
    """Delete workspace and all its data."""
    ok = delete_workspace(ws_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Clean up SSE log queue
    from app.services.logger import remove_queue
    remove_queue(ws_id)
    return {"deleted": True}


@router.post("/workspace/{ws_id}/scan")
async def scan_workspace(ws_id: str):
    """Scan workspace directory, return file tree."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return scan_folder(ws_id)


@router.post("/workspace/{ws_id}/index")
async def index_workspace(ws_id: str, body: dict):
    """Index selected scripts. body: {scripts: ["path1.sql", ...]}"""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    scripts = body.get("scripts", [])
    if not scripts:
        # Auto-select all SQL files from scan
        tree = scan_folder(ws_id)
        scripts = _collect_sql_files(tree)
    
    result = index_scripts(ws_id, scripts)
    return result



@router.get("/workspace/{ws_id}/status")
async def get_workspace_status(ws_id: str):
    """Poll workspace indexing progress."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    progress = get_index_progress(ws_id)
    status = get_index_status(ws_id)
    return {"workspace_id": ws_id, "progress": progress, "index_status": status}


@router.post("/workspace/{ws_id}/filter-config")
async def upload_filter_config(ws_id: str,
                                script_table: UploadFile = File(None),
                                table_col: UploadFile = File(None)):
    """Upload CSV filter files to narrow the table/field index.
    
    File 1 (script_table): SCRIPT_NAME, TABLE_NAME columns
    File 2 (table_col): SYSTEM, TABLE_NAME, COL_NAME, COL_COMMENT columns
    
    If neither file is uploaded, clears any active filter (show all).
    Stores filtered_index.json in workspace cache.
    """
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    cache_dir = get_workspace_dir(ws_id) / "cache"

    # Parse CSV files
    allowed_scripts = None  # None = no filter
    allowed_tables = None
    allowed_columns = None
    script_table_tables = None  # file 1 table scope (A), for R19 intersection
    distinct_scripts = set()    # Bug 52: raw SCRIPT_NAME values from file 1 rows
    script_table_rows = []      # file 1 rows (for SQL-evidence lookup of table→scripts)
    table_col_tables = set()    # file 2 table scope (B), for R19 intersection
    table_columns = {}          # file 2: table -> set(columns) (Bug 51/R19)
    ignored_count = 0           # B − A: table_col tables outside script scope
    ignored_tables = set()      # B − A set itself (F4, for the payload)
    file2_present = False       # table_col.csv was uploaded
    empty_intersection = False  # both files, no common table (Bug 51)

    # ── R16: Filter diagnostic logging ──
    diag_lines = []
    W = 80
    def _diag_box(header, lines):
        box = [f"┌─ {header} " + "─" * max(0, W - len(header) - 4) + "┐"]
        for ln in lines:
            box.append(f"│ {ln.ljust(W-4)}│")
        box.append(f"└{'─'*(W-2)}┘")
        return box
    diag_lines.append(("profile", f"┌─ FILTER DIAGNOSTIC ─{'─'*60}┐"))

    if script_table and script_table.filename:
        raw = (await script_table.read()).decode("utf-8", errors="replace")
        allowed_scripts = set()
        allowed_tables = set()
        reader = csv.DictReader(io.StringIO(raw))
        headers1 = reader.fieldnames or []
        rows = list(reader)
        row_count = len(rows)
        script_table_rows = rows  # keep for SQL-evidence diagnostics
        for row in rows:
            sn = row.get("SCRIPT_NAME", "").strip()
            tn = row.get("TABLE_NAME", "").strip()
            if sn:
                distinct_scripts.add(sn)
                allowed_scripts.add(sn)
                allowed_scripts.add(os.path.basename(sn))
                if not sn.lower().endswith('.sql'):
                    allowed_scripts.add(sn + '.sql')
                    allowed_scripts.add(os.path.basename(sn) + '.sql')
            if tn: allowed_tables.add(tn)
        # Diagnostic: file 1
        diag_lines.append(("profile", f"│ File 1 (script_table): {script_table.filename}  rows={row_count}  headers={','.join(headers1)}".ljust(79)+"│"))
        for i, row in enumerate(rows[:2]):
            diag_lines.append(("profile", f"│   Sample {i+1}: {row.get('SCRIPT_NAME','?')}→{row.get('TABLE_NAME','?')}".ljust(79)+"│"))
        # Bug 52: report distinct scripts; variants (path/.sql) shown separately
        diag_lines.append(("profile", f"│   Parsed: {len(distinct_scripts)} scripts ({len(allowed_scripts)} matching variants), {len(allowed_tables)} tables".ljust(79)+"│"))
        if row_count == 0:
            diag_lines.append(("profile", f"│ ⚠ No data parsed. Check headers: SCRIPT_NAME, TABLE_NAME".ljust(79)+"│"))
        script_table_tables = set(allowed_tables) if allowed_tables else set()

    if table_col and table_col.filename:
        raw = (await table_col.read()).decode("utf-8", errors="replace")
        file2_present = True
        if allowed_tables is None:
            allowed_tables = set()
        allowed_columns = set()
        reader = csv.DictReader(io.StringIO(raw))
        headers2 = reader.fieldnames or []
        rows = list(reader)
        row_count = len(rows)
        col_only_count = 0      # F3: rows with COL_NAME but empty TABLE_NAME
        for row in rows:
            tn = row.get("TABLE_NAME", "").strip()
            cn = row.get("COL_NAME", "").strip()
            if tn:
                allowed_tables.add(tn)
                table_col_tables.add(tn)
                if cn:
                    table_columns.setdefault(tn, set()).add(cn)
                    allowed_columns.add(cn)
            elif cn:
                col_only_count += 1
        # Diagnostic: file 2
        diag_lines.append(("profile", f"│ File 2 (table_col): {table_col.filename}  rows={row_count}  headers={','.join(headers2)}".ljust(79)+"│"))
        for i, row in enumerate(rows[:2]):
            diag_lines.append(("profile", f"│   Sample {i+1}: {row.get('TABLE_NAME','?')}→{row.get('COL_NAME','?')}".ljust(79)+"│"))
        diag_lines.append(("profile", f"│   Parsed: {len(allowed_columns)} columns, {len(allowed_tables)} tables".ljust(79)+"│"))
        if row_count == 0:
            diag_lines.append(("profile", f"│ ⚠ No data parsed. Check headers: TABLE_NAME, COL_NAME".ljust(79)+"│"))
        if col_only_count > 0:
            diag_lines.append(("profile", ("│ ⚠ %d row(s) had COL_NAME but empty TABLE_NAME — dropped"
                                           % col_only_count).ljust(79)+"│"))

    # ── Bug 51/R19: two-file intersection — effective table scope = A ∩ B ──
    if script_table_tables is not None:
        if allowed_tables is None:
            allowed_tables = set()
        if file2_present:
            # allowed_tables is currently A ∪ B; reduce it to A ∩ B by
            # intersecting with BOTH scopes (&= A alone would just restore A).
            ignored_tables = table_col_tables - script_table_tables      # B − A
            ignored_count = len(ignored_tables)
            allowed_tables &= script_table_tables
            allowed_tables &= table_col_tables
            # Restrict columns to effective tables
            if table_columns:
                allowed_columns = {cn for t, cols in table_columns.items()
                                   if t in allowed_tables for cn in cols}
            if not allowed_tables:
                # Bug 51 edge case: no common table — the filter stays active
                # but matches nothing (0 tables / 0 fields).
                empty_intersection = True
        else:
            # file-1-only: scope stays A (no column restriction)
            allowed_tables &= script_table_tables

    # If neither file uploaded, clear filter
    if allowed_scripts is None and allowed_tables is None and allowed_columns is None:
        fp = cache_dir / "filtered_index.json"
        if fp.exists():
            fp.unlink()
        return {"filtered": False, "message": "Filter cleared — showing all indexed entries"}

    # Load full indexes
    import json
    ti_path = cache_dir / "table_index.json"
    fi_path = cache_dir / "field_index.json"
    ti = json.loads(ti_path.read_text()) if ti_path.exists() else {}
    fi = json.loads(fi_path.read_text()) if fi_path.exists() else {}

    # Filter table_index
    filtered_ti = {}
    for tname, tdata in ti.items():
        # F2: `is not None` — an EMPTY allowed_tables set (filter active but
        # matching nothing) must drop every table; a falsy check would keep all.
        if allowed_tables is not None and tname not in allowed_tables:
            continue
        filtered_scripts = [s for s in tdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
        filtered_fields = [f for f in tdata.get("fields", [])
                          if allowed_columns is None or f in allowed_columns]
        if filtered_scripts or filtered_fields:
            filtered_ti[tname] = {
                "scripts": filtered_scripts,
                "fields": filtered_fields,
            }

    # Filter field_index
    filtered_fi = {}
    for fname, fdata in fi.items():
        # F2: same empty-set semantics as the table guard above.
        if allowed_columns is not None and fname not in allowed_columns:
            continue
        filtered_scripts = [s for s in fdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
        filtered_tables = [t for t in fdata.get("tables", [])
                          if allowed_tables is None or t in allowed_tables]
        if filtered_scripts or filtered_tables:
            filtered_fi[fname] = {
                "scripts": filtered_scripts,
                "tables": filtered_tables,
            }

    # Bug 51 edge case: empty intersection → filter stays active, matches nothing
    if empty_intersection:
        filtered_ti = {}
        filtered_fi = {}

    # Save filtered index
    (cache_dir / "filtered_index.json").write_text(json.dumps({
        "table_index": filtered_ti,
        "field_index": filtered_fi,
    }, indent=2))

    # ── Bug 51/R19: diagnostic — table_col tables ignored by the intersection ──
    if script_table_tables is not None and allowed_tables is not None:
        if ignored_count > 0:
            diag_lines.append(("profile", ("│ R19: ignored %d tables from table_col.csv (not in script_table scope)" % ignored_count).ljust(79)+"│"))
        if empty_intersection:
            diag_lines.append(("profile", "│ no common tables — check CSVs".ljust(79)+"│"))
            # F5: case-insensitive near-match hint — A (script_table) vs the
            # ORIGINAL B (table_col) may differ only by case, e.g. STG_CUSTOMERS
            # vs stg_customers; show it even when A∩B is empty. table_col_tables
            # still holds B here (allowed_tables was reduced to A∩B = ∅).
            seen_pairs = set()
            for a in sorted(script_table_tables):
                for b in sorted(table_col_tables):
                    if a != b and a.lower() == b.lower() and (b, a) not in seen_pairs:
                        seen_pairs.add((a, b))
                        diag_lines.append(("profile", ("│ ⚠ case mismatch? A has %s, B has %s"
                                                       % (a, b)).ljust(79)+"│"))
                        if len(seen_pairs) >= 5:
                            break
                if len(seen_pairs) >= 5:
                    break

    # ── Bug 52+: per-common-table match diagnostics ──
    # Shows why intersection tables survive or drop: index script names vs
    # CSV variants side by side (case/path/extension mismatches become visible).
    if script_table_tables is not None and allowed_tables is not None and ti:
        common_tables = sorted(allowed_tables & script_table_tables)
        diag_lines.append(("profile", ("│ Common tables (A∩B): %d — per-table match:  [index total: %d tables]"
                                       % (len(common_tables), len(ti))).ljust(79)+"│"))

        # SQL-evidence machinery: script file lookup + analysis cache (extractor
        # column vars), used to log tables whose RESULT has no fields so the
        # user can manually verify the SQL (parse bug vs genuinely absent).
        ws_dir = get_workspace_dir(ws_id)
        scripts_dir = ws_dir / "scripts"
        cache_dir = ws_dir / "cache"
        analysis_by_script = {}  # script_name (+ basename) -> analysis dict
        try:
            if cache_dir.exists():
                for af in sorted(cache_dir.glob("analysis_*.json")):
                    try:
                        ad = json.loads(af.read_text())
                        sn = ad.get("script_name", "")
                        if sn:
                            analysis_by_script.setdefault(sn, ad)
                            analysis_by_script.setdefault(os.path.basename(sn), ad)
                    except Exception:
                        pass
        except Exception:
            pass

        def _resolve_script(name: str):
            """Locate a script file by CSV/index name (path, basename, ±.sql)."""
            if not name:
                return None
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

        shown_drop_detail = 0
        shown_sql = 0
        for tname in common_tables[:15]:
            idx_scripts = ti.get(tname, {}).get("scripts", [])
            idx_fields = ti.get(tname, {}).get("fields", [])
            matched = [s for s in idx_scripts
                       if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
            kept = tname in filtered_ti
            nfields = len(filtered_ti.get(tname, {}).get("fields", [])) if kept else 0
            # fields N/M: N = kept in filter, M = total in index (divergence
            # means the table's index fields aren't among the CSV columns in
            # scope — see the field-detail lines below)
            diag_lines.append(("profile", ("│   %s %-35s scripts %d/%d fields %d/%d"
                                           % ("KEEP" if kept else "DROP", tname[:35],
                                              len(matched), len(idx_scripts),
                                              nfields, len(idx_fields))).ljust(79)+"│"))
            if not kept and not matched and shown_drop_detail < 6:
                shown_drop_detail += 1
                if idx_scripts:
                    # Table IS in the index but its scripts don't match the CSV
                    for s in idx_scripts[:2]:
                        diag_lines.append(("profile", ("│     index script: %r" % s).ljust(79)+"│"))
                    for v in sorted(allowed_scripts)[:4]:
                        diag_lines.append(("profile", ("│     csv variant:  %r" % v).ljust(79)+"│"))
                else:
                    # Table has NO index entry under this exact name — check
                    # for close matches (case / suffix) to explain the absence.
                    similar = [t for t in ti
                               if len(t) >= 4  # skip alias noise (c, o, sc, ...)
                               and (t.lower() == tname.lower()
                                    or tname.lower() in t.lower()
                                    or t.lower() in tname.lower())]
                    if similar:
                        diag_lines.append(("profile", ("│     index has similar: %s" % similar[:4]).ljust(79)+"│"))
                    else:
                        diag_lines.append(("profile", "│     NOT in index — no similar table (scripts missing/not uploaded?)".ljust(79)+"│"))
            # Field divergence: kept table whose index fields got filtered out
            elif kept and nfields < len(idx_fields) and shown_drop_detail < 6:
                shown_drop_detail += 1
                if not idx_fields:
                    diag_lines.append(("profile", "│     index has no fields for this table".ljust(79)+"│"))
                else:
                    diag_lines.append(("profile", ("│     index fields: %s" % idx_fields[:4]).ljust(79)+"│"))
                    diag_lines.append(("profile", ("│     csv columns in scope: %s"
                                                   % sorted(allowed_columns)[:4] if allowed_columns else "[]").ljust(79)+"│"))
            # SQL evidence: log every common table whose RESULT has no fields
            # (nfields == 0 — covers both 0/0 and 0/N), with the actual SQL
            # lines and extractor columns, so the user can verify manually.
            if nfields == 0 and shown_sql < 4:
                shown_sql += 1
                cand_scripts = set(idx_scripts)
                for row in script_table_rows:
                    if row.get("TABLE_NAME", "").strip() == tname:
                        sn = row.get("SCRIPT_NAME", "").strip()
                        if sn:
                            cand_scripts.add(sn)
                if not cand_scripts:
                    diag_lines.append(("profile", ("│   [%s] no script declares this table" % tname[:30]).ljust(79)+"│"))
                    continue
                diag_lines.append(("profile", ("│   [%s] SQL evidence — scripts: %s"
                                               % (tname[:30], sorted(cand_scripts)[:3])).ljust(79)+"│"))
                for cname in sorted(cand_scripts)[:2]:
                    sp = _resolve_script(cname)
                    if not sp:
                        diag_lines.append(("profile", ("│     script %r — FILE NOT FOUND in workspace" % cname).ljust(79)+"│"))
                        continue
                    try:
                        sql_txt = sp.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        sql_txt = ""
                    hit_lines = [ln for ln in sql_txt.split("\n") if tname.lower() in ln.lower()]
                    if not hit_lines:
                        diag_lines.append(("profile", ("│     script %s — table name NOT found in SQL text" % cname).ljust(79)+"│"))
                        continue
                    diag_lines.append(("profile", ("│     script %s — %d line(s) mention it:"
                                                   % (cname, len(hit_lines))).ljust(79)+"│"))
                    for ln in hit_lines[:3]:
                        diag_lines.append(("profile", ("│       %s" % ln.strip()[:74]).ljust(79)+"│"))
                    ad = analysis_by_script.get(cname) or analysis_by_script.get(os.path.basename(cname))
                    if ad:
                        cols = [v.get("name", "") for v in ad.get("variables", [])
                                if v.get("variable_type") == "column"]
                        rel = []
                        for v in ad.get("variables", []):
                            if v.get("variable_type") != "column":
                                continue
                            nm = v.get("name", "")
                            src = [s.lower() for s in v.get("source_tables", [])]
                            if tname.lower() in nm.lower() or tname.lower() in src:
                                rel.append(nm)
                        diag_lines.append(("profile", ("│     extractor columns: %d total, %d related to %s"
                                                       % (len(cols), len(rel), tname[:24])).ljust(79)+"│"))
                        if rel:
                            diag_lines.append(("profile", ("│       related: %s" % rel[:6]).ljust(79)+"│"))
                    else:
                        diag_lines.append(("profile", ("│     analysis cache for %s — NOT FOUND" % cname).ljust(79)+"│"))
        if len(common_tables) > 15:
            diag_lines.append(("profile", ("│   ... %d more common tables" % (len(common_tables)-15)).ljust(79)+"│"))
        if distinct_scripts:
            diag_lines.append(("profile", ("│ CSV script sample: %s" % sorted(distinct_scripts)[:5]).ljust(79)+"│"))

    # ── R16: Diagnostic result ──
    diag_lines.append(("profile", f"│ Result: {len(filtered_ti)} tables, {len(filtered_fi)} fields in filtered index".ljust(79)+"│"))
    diag_lines.append(("profile", f"└{'─'*78}┘"))
    for stage, msg in diag_lines:
        _push(ws_id, stage, msg)

    # ── F4: payload extras — ignored set (B − A) + human warning ──
    warning = None
    if empty_intersection:
        warning = "No common tables between script_table.csv and table_col.csv — filter matches nothing"
    elif ignored_count > 0:
        warning = "%d table(s) from table_col.csv ignored (not in script_table.csv scope)" % ignored_count

    return {
        "filtered": True,
        "table_count": len(filtered_ti),
        "field_count": len(filtered_fi),
        "filtered_tables": list(filtered_ti.keys()),
        "filtered_fields": list(filtered_fi.keys()),
        "ignored_count": ignored_count,
        "ignored_tables": sorted(ignored_tables),
        "warning": warning,
    }


@router.delete("/workspace")
async def cleanup_workspaces():
    """Delete ALL workspaces. Use with caution."""
    removed = cleanup_all_workspaces()
    return {"cleaned": removed}

@router.get("/workspace/{ws_id}/export-config")
async def get_export_config_endpoint(ws_id: str):
    """Get current SQL export config (or defaults if none uploaded)."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return get_export_config(ws_id)


@router.put("/workspace/{ws_id}/export-config")
async def update_export_config(ws_id: str, body: dict):
    """Save SQL export config. Body: partial or full config dict."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    config = save_export_config(ws_id, body)
    return config


@router.delete("/workspace/{ws_id}/export-config")
async def delete_export_config(ws_id: str):
    """Reset SQL export config to defaults."""
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return reset_export_config(ws_id)


@router.get("/workspace/{ws_id}/export-config/default")
async def get_default_config():
    """Return the built-in default export config (read-only reference)."""
    return dict(DEFAULT_CONFIG)


@router.get("/workspace/{ws_id}/autocomplete")
async def autocomplete(ws_id: str, type: str = "table", q: str = ""):
    """Get autocomplete suggestions. type: 'table' or 'field'."""
    from app.services.folder_index_service import autocomplete as ac
    import json
    
    ws = get_workspace(ws_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    cache_dir = get_workspace_dir(ws_id) / "cache"
    index_path = cache_dir / (f"{type}_index.json")
    
    if not index_path.exists():
        return {"suggestions": []}
    
    index = json.loads(index_path.read_text())
    suggestions = ac(index, type, q)
    return {"suggestions": suggestions}


def _collect_sql_files(tree: dict) -> list:
    """Recursively collect all .sql file paths from a tree."""
    paths = []
    if tree.get("type") == "file" and tree.get("is_sql"):
        paths.append(tree["path"])
    for child in tree.get("children", []):
        paths.extend(_collect_sql_files(child))
    return paths
