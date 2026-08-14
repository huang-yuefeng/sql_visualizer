"""Filter service — CSV filter config parsing + filtered index build.

Extracted from `routers/workspace.py` (F6) following the project's
router/service split: routers stay HTTP-only, services own the logic.

Scope: file-1 (script_table) / file-2 (table_col) CSV parsing, the
A∩B intersection (Bug 51/R19), blank-COL_NAME semantics (R1), filter
application to table/field indexes, and the R16 diagnostic payload.

Also hosts the shared script resolver `resolve_script` (R5) — reused by
`folder_index_service` for its orphan-report SQL evidence.
"""
import asyncio
import csv
import io
import json
import os
from pathlib import Path

from fastapi import HTTPException

from app.services.logger import _push as _default_push
from app.services.workspace_service import get_workspace_dir

# L10: hard cap on filter-CSV uploads (zip uploads cap at 100 MB; these
# two CSVs were uncapped → OOM/500 on a giant file).
MAX_FILTER_CSV_BYTES = 20_000_000


def _decode_csv(raw: bytes) -> tuple[str, str]:
    """Decode filter-CSV bytes with encoding fallbacks (L11).

    utf-8-sig (also strips a UTF-8 BOM if present) → gb18030 (covers
    GBK/GB2312/Shift-JIS-adjacent CJK encodings common in filter CSVs) →
    latin-1 (never fails — every byte maps, so no data is silently lost).
    Returns (text, encoding) so the caller can log a hint when the file
    wasn't plain UTF-8.
    """
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def resolve_script(ws_id: str, name: str) -> Path | None:
    """Locate a script file by CSV/index name (path, basename, ±.sql).

    Shared resolver (R5): the filter's SQL-evidence diagnostics and the
    orphan-resolution report use the same tolerance — try as-is, with
    .sql appended, basename variants, then an rglob fallback.

    H1: `name` is user-controlled (filter CSV SCRIPT_NAME column), so every
    candidate is .resolve()d and must stay INSIDE the workspace scripts dir —
    absolute paths and `../` chains resolve to None instead of escaping.
    """
    if not name:
        return None
    scripts_dir = get_workspace_dir(ws_id) / "scripts"
    scripts_root = scripts_dir.resolve()
    cands = [name]
    if not name.lower().endswith(".sql"):
        cands.append(name + ".sql")
    for c in list(cands):
        cands.append(os.path.basename(c))
    for c in cands:
        p = (scripts_dir / c).resolve()
        if p.is_relative_to(scripts_root) and p.exists():
            return p
    for p in scripts_dir.rglob("*.sql"):
        if p.name in cands or str(p.relative_to(scripts_dir)) in cands:
            return p
    return None


async def apply_filter_config(ws_id: str, script_table, table_col, push=None) -> dict:
    """Parse the two filter CSVs and apply them to the table/field index.

    File 1 (script_table): SCRIPT_NAME, TABLE_NAME columns — script scope + table scope A.
    File 2 (table_col): SYSTEM, TABLE_NAME, COL_NAME, COL_COMMENT columns — table scope B
    + column scope. A row with TABLE_NAME but blank COL_NAME (R1) means the table is
    UNCONSTRAINED: all its fields pass the field filter.

    Two-file upload → effective table scope = A ∩ B (Bug 51/R19).
    If neither file is uploaded, clears any active filter (show all).
    Stores filtered_index.json in workspace cache.

    `push` is the SSE log hook (stage, msg) — the router passes its own
    `_push` binding so tests can intercept it; defaults to logger._push.
    """
    if push is None:
        push = _default_push

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
    unconstrained_tables = set()  # R1: tables with a blank-COL_NAME row (no column constraint)
    ignored_count = 0           # B − A: table_col tables outside script scope
    ignored_tables = set()      # B − A set itself (F4, for the payload)
    ignored_rows = 0            # F3: COL_NAME-only rows dropped by design (no TABLE_NAME)
    file2_present = False       # table_col.csv was uploaded
    empty_intersection = False  # both files, no common table (Bug 51)

    # ── R16: Filter diagnostic logging ──
    diag_lines = []
    diag_lines.append(("profile", f"┌─ FILTER DIAGNOSTIC ─{'─'*60}┐"))

    if script_table and script_table.filename:
        raw_bytes = await script_table.read()
        if len(raw_bytes) > MAX_FILTER_CSV_BYTES:
            raise HTTPException(status_code=400,
                                detail=f"script_table.csv too large (max {MAX_FILTER_CSV_BYTES} bytes)")
        raw, enc = _decode_csv(raw_bytes)
        allowed_scripts = set()
        allowed_tables = set()
        try:
            reader = csv.DictReader(io.StringIO(raw))
            headers1 = reader.fieldnames or []
            rows = list(reader)
            row_count = len(rows)
            script_table_rows = rows  # keep for SQL-evidence diagnostics
            for row in rows:
                # M5: short rows map missing trailing fields to None, not ""
                sn = (row.get("SCRIPT_NAME") or "").strip()
                tn = (row.get("TABLE_NAME") or "").strip()
                if sn:
                    distinct_scripts.add(sn)
                    allowed_scripts.add(sn)
                    allowed_scripts.add(os.path.basename(sn))
                    if not sn.lower().endswith('.sql'):
                        allowed_scripts.add(sn + '.sql')
                        allowed_scripts.add(os.path.basename(sn) + '.sql')
                # F5: table names are matched case-insensitively against the
                # index (STG_CUSTOMERS must match stg_customers) — fold at
                # parse time; index-side names are folded at predicate time.
                # Script names stay case-sensitive: they are real file paths
                # on a case-sensitive filesystem.
                if tn: allowed_tables.add(tn.lower())
        except HTTPException:
            raise
        except Exception as e:
            # M5: never let a malformed CSV surface as an unhandled 500.
            raise HTTPException(status_code=400,
                                detail=f"Invalid script_table.csv: {e}")
        # Diagnostic: file 1
        diag_lines.append(("profile", f"│ File 1 (script_table): {script_table.filename}  rows={row_count}  headers={','.join(headers1)}".ljust(79)+"│"))
        if enc != "utf-8-sig":
            diag_lines.append(("profile", f"│   encoding: {enc} (not UTF-8)".ljust(79)+"│"))
        for i, row in enumerate(rows[:2]):
            diag_lines.append(("profile", f"│   Sample {i+1}: {row.get('SCRIPT_NAME','?')}→{row.get('TABLE_NAME','?')}".ljust(79)+"│"))
        # Bug 52: report distinct scripts; variants (path/.sql) shown separately
        diag_lines.append(("profile", f"│   Parsed: {len(distinct_scripts)} scripts ({len(allowed_scripts)} matching variants), {len(allowed_tables)} tables".ljust(79)+"│"))
        if row_count == 0:
            diag_lines.append(("profile", f"│ ⚠ No data parsed. Check headers: SCRIPT_NAME, TABLE_NAME".ljust(79)+"│"))
        script_table_tables = set(allowed_tables) if allowed_tables else set()

    if table_col and table_col.filename:
        raw_bytes = await table_col.read()
        if len(raw_bytes) > MAX_FILTER_CSV_BYTES:
            raise HTTPException(status_code=400,
                                detail=f"table_col.csv too large (max {MAX_FILTER_CSV_BYTES} bytes)")
        raw, enc = _decode_csv(raw_bytes)
        file2_present = True
        if allowed_tables is None:
            allowed_tables = set()
        allowed_columns = set()
        tables_with_cols = set()  # N6: tables that have ≥1 COL_NAME row
        blank_row_tables = set()  # N6: tables with a blank-COL_NAME row
        try:
            reader = csv.DictReader(io.StringIO(raw))
            headers2 = reader.fieldnames or []
            rows = list(reader)
            row_count = len(rows)
            ignored_rows = 0        # F3: rows with COL_NAME but empty TABLE_NAME
            for row in rows:
                # M5: short rows map missing trailing fields to None, not ""
                # F5: fold table/column names to lowercase — matching against
                # the index is case-insensitive (STG_CUSTOMERS ↔ stg_customers).
                tn = (row.get("TABLE_NAME") or "").strip().lower()
                cn = (row.get("COL_NAME") or "").strip().lower()
                if tn:
                    allowed_tables.add(tn)
                    table_col_tables.add(tn)
                    if cn:
                        table_columns.setdefault(tn, set()).add(cn)
                        allowed_columns.add(cn)
                        tables_with_cols.add(tn)
                    else:
                        # R1: blank COL_NAME row → the table has NO column
                        # constraint (all its fields pass the field filter).
                        unconstrained_tables.add(tn)
                        blank_row_tables.add(tn)
                elif cn:
                    # F3: COL_NAME with no TABLE_NAME cannot be attached to
                    # any scope table — DROPPED BY DESIGN (it constrains
                    # nothing, and guessing a table would break the never-
                    # guess invariant). Counted (ignored_rows) so the drop
                    # is visible in the payload + diagnostic.
                    ignored_rows += 1
        except HTTPException:
            raise
        except Exception as e:
            # M5: never let a malformed CSV surface as an unhandled 500.
            raise HTTPException(status_code=400,
                                detail=f"Invalid table_col.csv: {e}")
        # Diagnostic: file 2
        diag_lines.append(("profile", f"│ File 2 (table_col): {table_col.filename}  rows={row_count}  headers={','.join(headers2)}".ljust(79)+"│"))
        if enc != "utf-8-sig":
            diag_lines.append(("profile", f"│   encoding: {enc} (not UTF-8)".ljust(79)+"│"))
        for i, row in enumerate(rows[:2]):
            diag_lines.append(("profile", f"│   Sample {i+1}: {row.get('TABLE_NAME','?')}→{row.get('COL_NAME','?')}".ljust(79)+"│"))
        diag_lines.append(("profile", f"│   Parsed: {len(allowed_columns)} columns, {len(allowed_tables)} tables".ljust(79)+"│"))
        if row_count == 0:
            diag_lines.append(("profile", f"│ ⚠ No data parsed. Check headers: TABLE_NAME, COL_NAME".ljust(79)+"│"))
        if ignored_rows > 0:
            diag_lines.append(("profile", ("│ ⚠ %d row(s) had COL_NAME but empty TABLE_NAME — dropped"
                                           % ignored_rows).ljust(79)+"│"))
        if unconstrained_tables:
            diag_lines.append(("profile", ("│ R1: %d table(s) have a blank COL_NAME row — unconstrained, all fields kept"
                                           % len(unconstrained_tables)).ljust(79)+"│"))
            # N6: a blank row silently WINS over column rows for the same
            # table — name them so a mixed CSV's intent is visible.
            blank_wins = blank_row_tables & tables_with_cols
            if blank_wins:
                diag_lines.append(("profile", ("│ R1: blank row wins for: %s"
                                               % ", ".join(sorted(blank_wins)[:5])).ljust(79)+"│"))

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

    # R1: blank-COL_NAME rows constrain nothing — restrict the unconstrained
    # set to the EFFECTIVE table scope (A∩B when both files; B otherwise).
    if allowed_tables is not None:
        unconstrained_tables &= allowed_tables

    # Load full indexes
    ti_path = cache_dir / "table_index.json"
    fi_path = cache_dir / "field_index.json"
    ti = json.loads(ti_path.read_text()) if ti_path.exists() else {}
    fi = json.loads(fi_path.read_text()) if fi_path.exists() else {}

    # ── User ruling (2026-08-14): the table-column CSV (File 2) is the
    # single source of truth for SCRIPT scope ──
    # allowed_scripts = ⋃ table_index[t]["scripts"] for every table `t`
    # listed in the table-column filter (File 2), and File 1 is IGNORED
    # for script scope (whether or not it is uploaded). This closes the
    # gap where uploading only File 2 left allowed_scripts = None → the
    # search ran over EVERY script referencing the field. When NO
    # table-column filter is uploaded, the File-1-derived scope (or None)
    # is preserved unchanged.
    if file2_present:
        _ti_lower = {t.lower(): t for t in ti}
        _scope_scripts = set()
        for _t in table_col_tables:
            _idx_key = _ti_lower.get(_t)
            if _idx_key:
                _scope_scripts.update(ti[_idx_key].get("scripts", []))
        allowed_scripts = _scope_scripts
        diag_lines.append(("profile", ("│ File 2 is the script-scope source of truth: "
                                       "%d script(s) across %d table(s)"
                                       % (len(allowed_scripts),
                                          len(table_col_tables))).ljust(79)+"│"))

    # Filter table_index
    filtered_ti = {}
    for tname, tdata in ti.items():
        # F2: `is not None` — an EMPTY allowed_tables set (filter active but
        # matching nothing) must drop every table; a falsy check would keep all.
        # F5: membership is case-insensitive (CSV names folded at parse).
        if (allowed_tables is not None
                and tname.lower() not in allowed_tables):
            continue
        filtered_scripts = [s for s in tdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
        # R1: an unconstrained table keeps ALL its fields regardless of
        # allowed_columns (blank-COL_NAME row in table_col.csv).
        filtered_fields = [f for f in tdata.get("fields", [])
                          if allowed_columns is None
                          or f.lower() in allowed_columns
                          or tname.lower() in unconstrained_tables]
        if filtered_scripts or filtered_fields:
            filtered_ti[tname] = {
                "scripts": filtered_scripts,
                "fields": filtered_fields,
            }

    # Filter field_index
    filtered_fi = {}
    for fname, fdata in fi.items():
        # F2: same empty-set semantics as the table guard above.
        # R1: a field also passes if it belongs to any unconstrained table.
        # F5: membership is case-insensitive (CSV names folded at parse).
        if allowed_columns is not None and fname.lower() not in allowed_columns \
                and not ({t.lower() for t in fdata.get("tables", [])} & unconstrained_tables):
            continue
        filtered_scripts = [s for s in fdata.get("scripts", [])
                           if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
        # M6: apply the SAME per-table predicate as the table pass (R1), so
        # filtered_fi[f]["tables"] stays symmetric with filtered_ti[t]["fields"]:
        # a field shared by an unconstrained table U and a constrained table C
        # (both allowed) lists U but NOT C — C's own filtered_ti omits the field.
        filtered_tables = [t for t in fdata.get("tables", [])
                          if allowed_tables is None
                          or (t.lower() in allowed_tables
                              and (allowed_columns is None or fname.lower() in allowed_columns
                                   or t.lower() in unconstrained_tables))]
        if filtered_scripts or filtered_tables:
            filtered_fi[fname] = {
                "scripts": filtered_scripts,
                "tables": filtered_tables,
            }

    # Bug 51 edge case: empty intersection → filter stays active, matches nothing
    if empty_intersection:
        filtered_ti = {}
        filtered_fi = {}

    # Save filtered index (L9: write off the event loop — large workspaces)
    await asyncio.to_thread(
        (cache_dir / "filtered_index.json").write_text,
        json.dumps({"table_index": filtered_ti, "field_index": filtered_fi}, indent=2),
    )

    # ── Bug 51/R19: diagnostic — table_col tables ignored by the intersection ──
    if script_table_tables is not None and allowed_tables is not None:
        if ignored_count > 0:
            diag_lines.append(("profile", ("│ R19: ignored %d tables from table_col.csv (not in script_table scope)" % ignored_count).ljust(79)+"│"))
        if empty_intersection:
            diag_lines.append(("profile", "│ no common tables — check CSVs".ljust(79)+"│"))

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
                        pass  # corrupt/partial analysis cache — skip, diagnostic-only
        except Exception:
            pass  # cache scan is diagnostic-only — missing cache must not break the filter

        # F5: common table names are lowercased CSV values — resolve each to
        # its original-case index key for the diagnostics below (exact first,
        # single case-variant fallback; ambiguous → None, never guess).
        ti_lower = {t.lower(): t for t in ti}
        filtered_ti_lower = {t.lower(): t for t in filtered_ti}
        shown_drop_detail = 0
        shown_sql = 0
        for tname in common_tables[:15]:
            idx_key = ti_lower.get(tname)
            idx_scripts = ti.get(idx_key, {}).get("scripts", []) if idx_key else []
            idx_fields = ti.get(idx_key, {}).get("fields", []) if idx_key else []
            matched = [s for s in idx_scripts
                       if allowed_scripts is None or s in allowed_scripts or os.path.basename(s) in allowed_scripts]
            kept = tname in filtered_ti_lower
            nfields = len(filtered_ti.get(filtered_ti_lower.get(tname), {}).get("fields", [])) if kept else 0
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
                    # F5: file-1 TABLE_NAME is folded at parse — compare folded
                    # here too (row names keep original case for display).
                    if (row.get("TABLE_NAME") or "").strip().lower() == tname:
                        sn = (row.get("SCRIPT_NAME") or "").strip()
                        if sn:
                            cand_scripts.add(sn)
                if not cand_scripts:
                    diag_lines.append(("profile", ("│   [%s] no script declares this table" % tname[:30]).ljust(79)+"│"))
                    continue
                diag_lines.append(("profile", ("│   [%s] SQL evidence — scripts: %s"
                                               % (tname[:30], sorted(cand_scripts)[:3])).ljust(79)+"│"))
                for cname in sorted(cand_scripts)[:2]:
                    sp = resolve_script(ws_id, cname)
                    if not sp:
                        diag_lines.append(("profile", ("│     script %r — FILE NOT FOUND in workspace" % cname).ljust(79)+"│"))
                        continue
                    try:
                        sql_txt = sp.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        sql_txt = ""  # unreadable script → no evidence lines (benign, diagnostic-only)
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
        push(ws_id, stage, msg)

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
        # F4/F3: ignored_rows is the ONE name for CSV-level drops (COL_NAME-only
        # rows); ignored_count/ignored_tables keep their intersection-exclusion
        # meaning (B − A). The two counters are disjoint.
        "ignored_rows": ignored_rows,
        "ignored_count": ignored_count,
        "ignored_tables": sorted(ignored_tables),
        "warning": warning,
    }
